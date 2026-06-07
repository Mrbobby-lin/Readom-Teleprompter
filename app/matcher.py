"""
文本匹配算法 - 核心模块

将语音识别结果与提词器原文进行匹配，
定位到当前朗读位置。

策略：三级递进匹配
1. 段落级 - 粗定位到段落
2. 句子级 - 精确定位到句子
3. 字符级 - 在句内追踪阅读进度
"""

import re
import logging

logger = logging.getLogger(__name__)


class TextMatcher:
    """文本匹配器 - 将语音识别文本匹配到原文位置"""

    # 相似度阈值，低于此值认为不匹配
    SIMILARITY_THRESHOLD = 0.30
    # 匹配确认阈值，高于此值直接确认匹配
    CONFIRM_THRESHOLD = 0.55
    # 防抖窗口大小（句子数）
    JITTER_WINDOW = 2
    # 最大向前跳转句子数（防止噪声匹配到后面的句子）
    MAX_FORWARD_JUMP = 1

    def __init__(self, text_manager):
        self.tm = text_manager          # TextManager 实例
        self.current_sent_idx = 0       # 当前句子索引
        self.current_char_idx = 0       # 当前字符位置（句内）
        self.confirmed_sent_idx = 0     # 已确认的句子位置
        self.total_sentences = 0        # 总句子数
        self.consecutive_mismatch = 0   # 连续不匹配计数
        self.history = []               # 匹配历史，用于防抖

    def reset(self):
        """重置匹配状态"""
        self.current_sent_idx = 0
        self.current_char_idx = 0
        self.confirmed_sent_idx = 0
        self.consecutive_mismatch = 0
        self.history = []
        # 重置所有句子的 is_read 状态
        for sent in self.tm.sentences:
            sent.is_read = False

    def set_total_sentences(self, total):
        """设置总句子数"""
        self.total_sentences = total

    def match(self, recognized_text):
        """
        核心匹配方法
        参数: recognized_text - 语音识别出的文本
        返回: dict {
            "sent_idx": int,          # 匹配到的句子索引
            "char_idx": int,          # 句内字符位置
            "confidence": float,      # 匹配置信度 0.0-1.0
            "is_new_sentence": bool,  # 是否跳到了新句子
            "is_confirmed": bool,     # 是否已确认（高置信度）
            "progress": float,        # 整体进度 0.0-1.0
            "text": str               # 当前句子文本
        }
        """
        if not recognized_text or not self.tm.has_text():
            return self._make_result(0, 0, 0, False)

        # 清理识别文本：去空格、标点
        clean_text = self._clean_text(recognized_text)
        if not clean_text:
            return self._make_result(
                self.current_sent_idx, self.current_char_idx, 0, False
            )

        # 第一步：尝试匹配句子
        best_match = self._find_best_sentence(clean_text)

        if best_match["sent_idx"] >= 0:
            self.consecutive_mismatch = 0
            new_idx = best_match["sent_idx"]
            confidence = best_match["similarity"]
            is_new = (new_idx != self.current_sent_idx)

            # 防跳变逻辑
            if is_new:
                # 限制向前跳转：最多跳 MAX_FORWARD_JUMP 句
                # 防止噪声文字匹配到后面的句子导致高亮飞跳
                if new_idx > self.current_sent_idx:
                    jump = new_idx - self.current_sent_idx
                    if jump > self.MAX_FORWARD_JUMP:
                        if confidence < self.CONFIRM_THRESHOLD:
                            logger.debug(
                                f"限制向前跳转: {self.current_sent_idx}→{new_idx} "
                                f"(conf={confidence:.2f}), 改为 +{self.MAX_FORWARD_JUMP}"
                            )
                            new_idx = self.current_sent_idx + self.MAX_FORWARD_JUMP
                            # 重算置信度
                            sent_text = self.tm.get_sentence_text(new_idx)
                            if sent_text:
                                confidence = self._calc_similarity(
                                    clean_text, self._clean_text(sent_text)
                                )

                new_idx = self._apply_anti_jitter(new_idx, confidence)

            self.current_sent_idx = new_idx
            self.current_char_idx = best_match.get("char_idx", 0)

            # 标记已读句子
            for i in range(self.current_sent_idx):
                if i < len(self.tm.sentences):
                    self.tm.sentences[i].is_read = True

            is_confirmed = confidence >= self.CONFIRM_THRESHOLD
            if is_confirmed:
                self.confirmed_sent_idx = self.current_sent_idx

            return self._make_result(
                self.current_sent_idx,
                self.current_char_idx,
                confidence,
                is_new,
                is_confirmed
            )
        else:
            # 没匹配到，增加不匹配计数
            self.consecutive_mismatch += 1
            # 尝试在当前位置附近找
            near_match = self._find_nearby(clean_text)
            if near_match["sent_idx"] >= 0:
                return self._make_result(
                    near_match["sent_idx"],
                    near_match.get("char_idx", 0),
                    near_match["similarity"] * 0.8,
                    False,
                    False
                )
            return self._make_result(
                self.current_sent_idx, self.current_char_idx, 0, False
            )

    def _find_best_sentence(self, clean_text):
        """
        在所有句子中找最佳匹配
        优先搜索当前位置附近的句子
        """
        search_range = 5  # 前后搜索范围
        start = max(0, self.current_sent_idx - search_range)
        end = min(self.total_sentences, self.current_sent_idx + search_range)

        best = {"sent_idx": -1, "similarity": 0, "char_idx": 0}

        # 先在当前位置附近搜索
        for i in range(start, end):
            sent_text = self.tm.get_sentence_text(i)
            if sent_text:
                sim = self._calc_similarity(clean_text, sent_text)
                if sim > best["similarity"]:
                    best = {"sent_idx": i, "similarity": sim, "char_idx": 0}

        # 如果附近没找到好的，扩大到全文搜索
        # 但加大阈值：全文匹配需要更高的相似度才能跳转
        fulltext_min = self.SIMILARITY_THRESHOLD + 0.15  # 0.45
        if best["similarity"] < fulltext_min:
            for i in range(self.total_sentences):
                if i < start or i >= end:
                    sent_text = self.tm.get_sentence_text(i)
                    if sent_text:
                        sim = self._calc_similarity(clean_text, sent_text)
                        # 远距离匹配需要更高阈值
                        distance = abs(i - self.current_sent_idx)
                        distance_penalty = max(0.7, 1.0 - distance * 0.05)
                        adjusted = sim * distance_penalty
                        if adjusted > best["similarity"]:
                            best = {
                                "sent_idx": i,
                                "similarity": sim,  # 保存原始相似度
                                "char_idx": 0
                            }

        # 如果找到，计算句内字符位置
        if best["sent_idx"] >= 0 and best["similarity"] > 0:
            sent_text = self.tm.get_sentence_text(best["sent_idx"])
            clean_sent = self._clean_text(sent_text)
            best["char_idx"] = self._calc_char_position(
                clean_text, clean_sent
            )

        return best

    def _find_nearby(self, clean_text):
        """在当前位置附近找（宽松匹配）"""
        start = max(0, self.current_sent_idx - 2)
        end = min(self.total_sentences, self.current_sent_idx + 3)

        best = {"sent_idx": -1, "similarity": 0, "char_idx": 0}

        for i in range(start, end):
            # 取更宽的上下文
            ctx = self.tm.get_context(i, window=1)
            if ctx:
                sim = self._calc_similarity(clean_text, ctx)
                if sim > best["similarity"]:
                    best = {"sent_idx": i, "similarity": sim, "char_idx": 0}
                    if sim > 0.25:
                        break

        return best

    def _calc_similarity(self, text_a, text_b):
        """
        计算两个文本的相似度
        使用字符级 Jaccard 相似度 + 最长公共子序列权重
        """
        if not text_a or not text_b:
            return 0.0

        # 字符集 Jaccard 相似度
        set_a = set(text_a)
        set_b = set(text_b)
        if not set_a or not set_b:
            return 0.0

        intersection = set_a & set_b
        union = set_a | set_b
        jaccard = len(intersection) / len(union)

        # 字符重叠率（识别文本中有多少字符在原文中）
        overlap = sum(1 for c in text_a if c in set_b)
        coverage = overlap / len(text_a) if text_a else 0

        # 加权组合
        similarity = jaccard * 0.4 + coverage * 0.6

        return similarity

    def _calc_char_position(self, recognized, sentence):
        """
        计算识别文本对应在句子中的字符位置
        """
        if not recognized or not sentence:
            return 0

        # 找到最长的前缀匹配
        max_match = 0
        for i in range(1, min(len(recognized), len(sentence)) + 1):
            if recognized[:i] in sentence:
                max_match = i

        # 根据匹配长度估算位置比例
        ratio = max_match / len(sentence) if sentence else 0
        return int(ratio * len(sentence))

    def _apply_anti_jitter(self, new_idx, confidence):
        """防跳变：防止位置来回跳动"""
        # 如果置信度很高，直接接受
        if confidence >= self.CONFIRM_THRESHOLD:
            return new_idx

        # 记录到历史
        self.history.append(new_idx)
        if len(self.history) > self.JITTER_WINDOW:
            self.history.pop(0)

        # 如果历史中有多个相同位置，取众数
        if len(self.history) >= 2:
            from collections import Counter
            counter = Counter(self.history)
            most_common = counter.most_common(1)[0]
            if most_common[1] >= 2:
                return most_common[0]

        # 默认保持当前位置
        return self.current_sent_idx

    def calc_mismatch(self, recognized_text, sentence_text):
        """
        计算朗读错误位置（读错标红）
        比较识别文本和原文，返回原文中不匹配的字符区间

        Returns:
            list of (start, end)  — 原文中匹配失败的位置（左闭右开）
        """
        if not recognized_text or not sentence_text:
            return []

        # 清理文本（去标点空白）
        clean_rec = self._clean_text(recognized_text)
        clean_sent = self._clean_text(sentence_text)

        if not clean_rec or not clean_sent:
            return []

        # 使用 difflib 做序列对齐
        import difflib
        matcher = difflib.SequenceMatcher(None, clean_rec, clean_sent)

        # 收集 sentence 侧的不匹配区域
        # get_opcodes 返回将 clean_rec 转成 clean_sent 的操作
        # 'replace' = 原文此处与朗读不同
        # 'delete'  = 朗读多了（原文没有）
        # 'insert'  = 原文此处没被朗读
        # 'equal'   = 匹配
        mismatch_positions = set()
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "insert"):
                # 原文中 j1:j2 的部分朗读不正确
                for pos in range(j1, j2):
                    mismatch_positions.add(pos)

        if not mismatch_positions:
            return []

        # 将位置映射回原文（含标点）
        # 构建 clean_index → original_index 的映射
        clean_to_orig = []
        for i, ch in enumerate(sentence_text):
            if re.match(r"[一-鿿\w]", ch):  # 中文字符或字母数字
                clean_to_orig.append(i)

        # 将 clean 位置映射到原文位置
        orig_ranges = []
        for pos in sorted(mismatch_positions):
            if pos < len(clean_to_orig):
                orig_ranges.append(clean_to_orig[pos])

        if not orig_ranges:
            return []

        # 合并连续区间
        ranges = []
        start = orig_ranges[0]
        end = orig_ranges[0]
        for pos in orig_ranges[1:]:
            if pos == end + 1:
                end = pos
            else:
                ranges.append((start, end + 1))
                start = pos
                end = pos
        ranges.append((start, end + 1))

        return ranges

    def _clean_text(self, text):
        """清理文本：去空白、标点、统一大小写"""
        if not text:
            return ""
        # 去除所有空白字符
        text = re.sub(r"\s+", "", text)
        # 去除常见标点
        text = re.sub(r"[，。！？、；：""''（）【】《》\-\~\s]", "", text)
        # 统一英文字母大小写
        text = text.lower()
        return text

    def _make_result(
        self, sent_idx, char_idx, confidence,
        is_new=False, is_confirmed=False
    ):
        """构造返回结果"""
        progress = 0.0
        if self.total_sentences > 1:
            progress = sent_idx / (self.total_sentences - 1)

        sent_text = ""
        if 0 <= sent_idx < len(self.tm.sentences):
            sent_text = self.tm.sentences[sent_idx].text

        # 计算读错位置（当前句子才需要）
        mismatch_ranges = []
        if confidence > 0 and sent_text and 0 <= sent_idx < len(self.tm.sentences):
            # 从 result 中拿原始 recognized_text（这里取巧了，需要传进来）
            pass  # mismatch 在外部计算

        return {
            "sent_idx": sent_idx,
            "char_idx": char_idx,
            "confidence": confidence,
            "is_new_sentence": is_new,
            "is_confirmed": is_confirmed,
            "progress": min(progress, 1.0),
            "text": sent_text,
            "mismatch_ranges": [],  # 由外部填充
        }
