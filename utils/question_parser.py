# utils/question_parser.py

from bs4 import BeautifulSoup
from typing import Dict, List, Any, Optional
import re
import json

class SATQuestionParser:
    """SAT 题目解析器"""

    def __init__(self):
        self.question_patterns = {
            'multiple_choice': r'^\s*[A-D]\.',
            'grid_in': r'^\s*Grid-in',
            'true_false': r'^\s*True\s*\/\s*False'
        }

    def parse_question_block(self, html: str) -> List[Dict[str, Any]]:
        """解析题目块，返回题目列表"""
        soup = BeautifulSoup(html, 'html.parser')
        questions = []

        # 查找题目容器
        question_containers = soup.select('.question-container, [data-testid*="question"], .sat-question')

        for container in question_containers:
            question_data = self._parse_single_question(container)
            if question_data:
                questions.append(question_data)

        # 如果没有找到容器，尝试解析整个页面
        if not questions:
            question_data = self._parse_single_question(soup)
            if question_data:
                questions.append(question_data)

        return questions

    def _parse_single_question(self, soup) -> Optional[Dict[str, Any]]:
        """解析单个题目"""
        try:
            question_data = {
                'id': self._extract_question_id(soup),
                'type': self._determine_question_type(soup),
                'subject': self._extract_subject(soup),
                'question_text': self._extract_question_text(soup),
                'options': self._extract_options(soup),
                'correct_answer': self._extract_correct_answer(soup),
                'explanation': self._extract_explanation(soup),
                'tags': self._extract_tags(soup),
                'difficulty': self._estimate_difficulty(soup),
                'source': 'College Board SAT'
            }

            # 验证必要字段
            if not question_data['question_text']:
                return None

            return question_data

        except Exception as e:
            print(f"解析题目失败: {e}")
            return None

    def _extract_question_id(self, soup) -> str:
        """提取题目 ID"""
        # 尝试多种方式获取 ID
        id_elem = soup.select_one('[data-question-id], [id*="question"], .question-id')
        if id_elem:
            return id_elem.get('data-question-id') or id_elem.get('id') or id_elem.text.strip()

        # 从 URL 或文本中提取
        text = soup.get_text()
        id_match = re.search(r'Question\s*(\d+)', text, re.IGNORECASE)
        if id_match:
            return f"q_{id_match.group(1)}"

        return f"q_{hash(str(soup)[:50])}"

    def _determine_question_type(self, soup) -> str:
        """确定题目类型"""
        text = soup.get_text()

        if re.search(r'Grid-in|grid.*in', text, re.IGNORECASE):
            return 'grid_in'
        elif re.search(r'True.*False|False.*True', text, re.IGNORECASE):
            return 'true_false'
        else:
            return 'multiple_choice'

    def _extract_subject(self, soup) -> str:
        """提取科目"""
        # 从页面标题或元数据中提取
        title_elem = soup.select_one('title, h1, .subject-title')
        if title_elem:
            title_text = title_elem.get_text().lower()
            if 'math' in title_text:
                return 'Math'
            elif 'reading' in title_text or 'writing' in title_text:
                return 'Reading and Writing'

        # 从 URL 或其他元数据
        url = soup.select_one('link[rel="canonical"]')
        if url and url.get('href'):
            href = url['href'].lower()
            if 'math' in href:
                return 'Math'
            elif 'reading' in href or 'writing' in href:
                return 'Reading and Writing'

        return 'Unknown'

    def _extract_question_text(self, soup) -> str:
        """提取问题文本"""
        # 查找问题文本容器
        question_elem = soup.select_one('.question-text, [data-testid*="question-text"], .question-stem, p:first-of-type')

        if question_elem:
            return question_elem.get_text(strip=True)

        # 备选：查找第一个段落或问题相关的文本
        paragraphs = soup.select('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            if len(text) > 20 and not re.match(r'^\s*[A-D]\.', text):
                return text

        return ""

    def _extract_options(self, soup) -> List[str]:
        """提取选项"""
        options = []

        # 查找选项元素
        option_elems = soup.select('.option, [data-testid*="option"], [class*="choice"], li[class*="option"]')

        for elem in option_elems:
            text = elem.get_text(strip=True)
            # 移除选项标签 (A. B. 等)
            text = re.sub(r'^[A-D]\.\s*', '', text)
            if text:
                options.append(text)

        # 如果没找到，尝试从文本中提取
        if not options:
            text = soup.get_text()
            option_matches = re.findall(r'[A-D]\.\s*([^A-D]+?)(?=[A-D]\.|$)', text, re.DOTALL)
            options = [opt.strip() for opt in option_matches if opt.strip()]

        return options

    def _extract_correct_answer(self, soup) -> str:
        """提取正确答案"""
        # 查找答案元素
        answer_elem = soup.select_one('.correct-answer, [data-testid*="answer"], .answer-key, [class*="correct"]')

        if answer_elem:
            text = answer_elem.get_text(strip=True)
            # 提取答案字母
            match = re.search(r'\b([A-D])\b', text, re.IGNORECASE)
            if match:
                return match.group(1).upper()

        # 从文本中查找
        text = soup.get_text()
        match = re.search(r'correct\s*answer\s*:\s*([A-D])', text, re.IGNORECASE)
        if match:
            return match.group(1).upper()

        return ""

    def _extract_explanation(self, soup) -> str:
        """提取解释"""
        explanation_elem = soup.select_one('.explanation, [data-testid*="explanation"], .answer-explanation, [class*="explain"]')

        if explanation_elem:
            return explanation_elem.get_text(strip=True)

        # 查找包含"explanation"或"because"的段落
        paragraphs = soup.select('p')
        for p in paragraphs:
            text = p.get_text(strip=True).lower()
            if 'explanation' in text or 'because' in text or 'correct' in text:
                return p.get_text(strip=True)

        return ""

    def _extract_tags(self, soup) -> List[str]:
        """提取标签/知识点"""
        tags = []

        # 查找标签元素
        tag_elems = soup.select('.tag, [data-testid*="tag"], .skill-tag, [class*="tag"]')

        for elem in tag_elems:
            tag_text = elem.get_text(strip=True)
            if tag_text:
                tags.append(tag_text)

        # 从文本中提取常见知识点
        text = soup.get_text().lower()
        knowledge_points = {
            'algebra': 'Algebra',
            'geometry': 'Geometry',
            'statistics': 'Data Analysis',
            'reading': 'Reading Comprehension',
            'grammar': 'Grammar',
            'vocabulary': 'Vocabulary'
        }

        for key, value in knowledge_points.items():
            if key in text and value not in tags:
                tags.append(value)

        return tags

    def _estimate_difficulty(self, soup) -> str:
        """估算难度"""
        text = soup.get_text().lower()

        # 简单的难度估算逻辑
        if 'hard' in text or 'difficult' in text:
            return 'Hard'
        elif 'medium' in text or 'moderate' in text:
            return 'Medium'
        else:
            return 'Easy'