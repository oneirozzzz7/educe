"""
DeepForge 领域路由器
基于 TF-IDF 的轻量级领域分类——零API调用，<10ms

训练数据来源：每个领域的种子问题集
推理方式：计算输入和各领域种子的余弦相似度，取top-2
"""
from __future__ import annotations

import math
import re
from collections import Counter


DOMAIN_SEEDS: dict[str, list[str]] = {
    "medical": [
        "头疼发烧感冒咳嗽症状治疗用药吃药看病就医检查诊断处方",
        "血压血糖心脏胃疼失眠过敏皮肤怀孕月经手术住院",
        "孩子发烧度怎么处理降温退烧药物剂量儿科",
    ],
    "legal": [
        "法律合同诉讼赔偿违法起诉律师仲裁判决法条法规维权",
        "劳动合同工资辞退社保公积金工伤解雇欠薪离职补偿",
        "租房押金房东房租合同纠纷违约责任版权侵权专利商标",
    ],
    "math": [
        "计算方程证明数学几何代数微积分概率统计函数极限求导积分",
        "矩阵向量三角对数因数质数根号有理数无理数集合",
        "求解等于多少概率排列组合公式定理推导验证",
    ],
    "tech": [
        "编程代码程序算法数据结构API框架前端后端数据库服务器",
        "Python Java JavaScript Go Rust SQL Linux Git Docker部署",
        "TCP HTTP进程线程并发设计模式微服务性能优化缓存Redis",
        "AI机器学习深度学习神经网络transformer attention CNN RNN训练推理",
    ],
    "finance": [
        "投资理财股票基金保险贷款利率收益回报风险资产房产",
        "税退休养老通货膨胀汇率期货期权债券银行信用卡",
        "可转债转股溢价率定投指数基金分红配置组合",
    ],
    "writing": [
        "写一篇写一段写一首作文文章论文报告文案诗散文小说剧本",
        "演讲稿邮件信摘要标题修改润色改写续写仿写翻译",
        "开场白致辞文风体裁修辞结构段落措辞语气",
    ],
    "psychology": [
        "心情情绪焦虑压力烦恼痛苦孤独自卑迷茫不开心难过",
        "伤心崩溃绝望恐惧害怕紧张失落愧疚好累好烦抑郁",
        "工作压力职业迷茫人际关系亲密关系自信心理咨询",
    ],
    "history": [
        "历史朝代皇帝战争革命事件年代世纪古代近代现代文明帝国",
        "秦汉唐宋明清春秋战国三国统一灭亡开国建立",
        "二战一战革命改革运动起义变法维新殖民独立",
        "安史之乱靖康之变鸦片战争甲午战争辛亥革命长征",
    ],
    "science": [
        "物理化学生物科学实验原子分子基因DNA进化量子相对论",
        "电磁光能量宇宙黑洞星球行星细胞蛋白质元素化学式",
        "反应定律定理光速引力波粒子加速器暗物质",
    ],
    "cooking": [
        "做菜炒菜烹饪菜谱食谱好吃红烧清蒸煎炸煮烤炖",
        "五花肉排骨鸡翅牛肉鱼虾豆腐蔬菜调料火候",
        "糖醋宫保麻婆回锅水煮清炒凉拌卤味腌制",
        "红烧肉糖醋排骨可乐鸡翅番茄炒蛋宫保鸡丁鱼香肉丝",
    ],
    "education": [
        "学习考试备考复习教育学校大学高考考研留学",
        "英语语文数学物理化学成绩学习方法记忆效率",
        "费曼技巧间隔重复主动回忆笔记思维导图提分",
    ],
}

DOMAIN_LABELS = {
    "medical": "医学", "legal": "法律", "math": "数学",
    "tech": "技术", "finance": "金融", "writing": "写作",
    "psychology": "心理", "history": "历史", "science": "科学",
    "cooking": "烹饪", "education": "教育",
}


def _tokenize(text: str) -> list[str]:
    """中英文混合分词"""
    tokens = re.findall(r'[a-zA-Z]{2,}', text.lower())
    cn = re.findall(r'[一-鿿]+', text)
    for seg in cn:
        for i in range(len(seg)):
            if i + 2 <= len(seg):
                tokens.append(seg[i:i+2])
    return tokens


class DomainRouter:
    """TF-IDF 领域路由器——<10ms，零API调用"""

    def __init__(self):
        self._domain_vectors: dict[str, Counter] = {}
        self._idf: dict[str, float] = {}
        self._build_index()

    def _build_index(self):
        """构建每个领域的TF-IDF向量"""
        all_docs = []
        for domain, seeds in DOMAIN_SEEDS.items():
            combined = " ".join(seeds)
            tokens = _tokenize(combined)
            self._domain_vectors[domain] = Counter(tokens)
            all_docs.append(set(tokens))

        # IDF
        n = len(all_docs)
        all_terms = set()
        for doc in all_docs:
            all_terms |= doc
        for term in all_terms:
            df = sum(1 for doc in all_docs if term in doc)
            self._idf[term] = math.log(n / (df + 1)) + 1

    def classify(self, query: str, top_k: int = 2) -> list[tuple[str, float]]:
        """分类——返回 top-k 领域和分数"""
        tokens = _tokenize(query)
        if not tokens:
            return [("general", 0.0)]

        query_vec = Counter(tokens)
        scores = {}

        for domain, domain_vec in self._domain_vectors.items():
            score = 0.0
            for term, count in query_vec.items():
                if term in domain_vec:
                    tf_q = count
                    tf_d = domain_vec[term]
                    idf = self._idf.get(term, 1.0)
                    score += tf_q * tf_d * idf * idf
            scores[domain] = score

        ranked = sorted(scores.items(), key=lambda x: -x[1])
        top = [(d, s) for d, s in ranked[:top_k] if s > 0]

        if not top:
            return [("general", 0.0)]
        return top


_router = DomainRouter()


def route_domain(query: str, top_k: int = 2) -> list[str]:
    """快速路由——返回最匹配的领域列表"""
    results = _router.classify(query, top_k)
    return [d for d, s in results]
