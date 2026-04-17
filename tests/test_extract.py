from utils.extract import extract_idiom_info, extract_recommendations


def test_extract_basic_structure():
    html = '''
    <div class="content definitions">
        <p><span class="dicpy">zhèng yì</span></p>
        <p>解释一</p>
        <p>解释二</p>
    </div>
    '''
    result = extract_idiom_info(html, "正义")
    assert result["structured_definitions"]
    assert result["structured_definitions"][0]["readings"][0]["pinyin"] == "zhèng yì"


def test_extract_recommendations():
    html = '<div class="nr-box"><a class="usual">农业国</a></div>'
    recs = extract_recommendations(html)
    assert "农业国" in recs
