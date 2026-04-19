# utils/ai_tagger.py

import json
import re
from typing import List, Dict, Any, Optional
import logging

class AITagger:
    """AI 自动标注题目知识点"""

    def __init__(self):
        # 预定义的 SAT 知识点映射
        self.knowledge_points = {
            'algebra': ['linear equations', 'systems of equations', 'quadratic equations', 'functions'],
            'geometry': ['coordinate geometry', 'triangles', 'circles', 'solids'],
            'data_analysis': ['statistics', 'probability', 'data interpretation'],
            'reading': ['reading comprehension', 'evidence-based reading', 'vocabulary'],
            'writing': ['grammar', 'punctuation', 'rhetoric', 'organization']
        }

        # 关键词映射
        self.keyword_mapping = {
            'linear': 'linear equations',
            'system': 'systems of equations',
            'quadratic': 'quadratic equations',
            'function': 'functions',
            'triangle': 'triangles',
            'circle': 'circles',
            'statistic': 'statistics',
            'probability': 'probability',
            'comprehension': 'reading comprehension',
            'grammar': 'grammar',
            'punctuation': 'punctuation'
        }

    def tag_question(self, question_data: Dict[str, Any], topics_data: Dict[str, Any]) -> Dict[str, Any]:
        """为题目自动标注知识点"""
        question_text = question_data.get('question_text', '').lower()
        explanation = question_data.get('explanation', '').lower()
        subject = question_data.get('subject', '').lower()

        # 合并文本进行分析
        full_text = f"{question_text} {explanation}"

        # 提取知识点
        detected_points = set()

        # 基于关键词匹配
        for keyword, point in self.keyword_mapping.items():
            if keyword in full_text:
                detected_points.add(point)

        # 基于主题匹配
        for topic_key, topic_info in topics_data.items():
            topic_title = topic_info.get('title', '').lower()
            topic_description = topic_info.get('description', '').lower()
            topic_keywords = topic_info.get('keywords', [])

            # 检查题目文本是否包含主题关键词
            for keyword in topic_keywords:
                if keyword.lower() in full_text:
                    detected_points.add(topic_key)
                    break

            # 检查主题标题和描述
            if topic_title in full_text or topic_description in full_text:
                detected_points.add(topic_key)

        # 更新题目数据
        tagged_question = question_data.copy()
        tagged_question['knowledge_points'] = list(detected_points)
        tagged_question['confidence_score'] = min(len(detected_points) * 0.2, 1.0)  # 简单置信度计算

        return tagged_question

    def build_topic_question_mapping(self, questions: List[Dict[str, Any]], topics_data: Dict[str, Any]) -> Dict[str, Any]:
        """生成题目-知识点映射报告"""
        mapping = {
            "total_questions": len(questions),
            "total_topics": len(topics_data),
            "topic_question_counts": {},
            "question_topic_distribution": {},
            "unmapped_questions": []
        }

        # 统计每个知识点的题目数量
        for topic_key in topics_data.keys():
            mapping["topic_question_counts"][topic_key] = 0

        # 分析每个题目的知识点分布
        for question in questions:
            question_id = question.get('id', 'unknown')
            knowledge_points = question.get('knowledge_points', [])

            if not knowledge_points:
                mapping["unmapped_questions"].append(question_id)
            else:
                mapping["question_topic_distribution"][question_id] = knowledge_points
                for point in knowledge_points:
                    if point in mapping["topic_question_counts"]:
                        mapping["topic_question_counts"][point] += 1

        return mapping