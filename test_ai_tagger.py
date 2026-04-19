#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 标注器测试脚本
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from utils.ai_tagger import AITagger
from utils.question_parser import SATQuestionParser

def test_ai_tagger():
    """测试 AI 标注器功能"""
    print("🧪 测试 AI 标注器...")

    # 创建标注器实例
    tagger = AITagger()

    # 创建问题解析器
    parser = SATQuestionParser()

    # 测试题目数据
    test_html = """
    <div class="question-block">
        <div class="question-text">
            What is the value of x in the equation 2x + 3 = 7?
        </div>
        <div class="options">
            <div class="option">A) 1</div>
            <div class="option">B) 2</div>
            <div class="option">C) 3</div>
            <div class="option">D) 4</div>
        </div>
        <div class="answer">B</div>
        <div class="explanation">Subtract 3 from both sides: 2x = 4, then divide by 2: x = 2</div>
    </div>
    """

    # 解析题目
    questions = parser.parse_question_block(test_html)
    if not questions:
        print("❌ 题目解析失败")
        return

    question = questions[0]
    print(f"📝 解析的题目: {question}")

    # 测试知识点数据
    test_topics = {
        "linear_equations": {
            "title": "Linear Equations",
            "description": "Solving equations of the form ax + b = c",
            "keywords": ["equation", "solve", "linear", "variable", "x"]
        },
        "algebra_basics": {
            "title": "Algebra Basics",
            "description": "Fundamental algebra concepts",
            "keywords": ["algebra", "equation", "variable"]
        }
    }

    # 使用 AI 标注器标注题目
    tagged_question = tagger.tag_question(question, test_topics)
    print(f"🏷️ 标注后的题目: {tagged_question}")

    # 测试映射报告生成
    mapping_report = tagger.build_topic_question_mapping([tagged_question], test_topics)
    print(f"📊 映射报告: {mapping_report}")

    print("✅ AI 标注器测试完成")

if __name__ == "__main__":
    test_ai_tagger()