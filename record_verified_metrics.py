"""Record the public pages independently checked on 2026-09-26."""
import json
from journal_metrics import REGISTRY, load_registry, merge_metrics, normalize

registry = load_registry()
values = [
    {'journal': 'Remote Sensing', 'indexing': 'SCIE', 'if_value': 4.3, 'if_year': 2025, 'if_release_year': 2026,
     'if_year_basis': '出版方主页明确2025年度；统计图截至2025年',
     'jcr_subjects': [
         {'quartile': 'Q1', 'subject': 'Geosciences, Multidisciplinary'},
         {'quartile': 'Q2', 'subject': 'Remote Sensing'},
         {'quartile': 'Q2', 'subject': 'Environmental Sciences'},
         {'quartile': 'Q2', 'subject': 'Imaging Science and Photographic Technology'}],
     'jcr_year_label': '出版方2026-09-26当前显示；分区年度未单列',
     'jcr_basis': 'MDPI统计页全部JCR学科；未以CiteScore代替',
     'sources': ['https://www.mdpi.com/journal/remotesensing', 'https://www.mdpi.com/journal/remotesensing/stats']},
    {'journal': 'Electronics', 'issn': '2079-9292', 'indexing': 'SCIE', 'if_value': 2.9,
     'if_year': 2025, 'if_release_year': 2026, 'cas': '计算机科学大类4区', 'cas_year': 2025,
     'if_year_basis': '出版方统计图截至2025年；LetPub显示2026年6月更新',
     'jcr_subjects': [
         {'quartile': 'Q2', 'subject': 'Engineering, Electrical and Electronic'},
         {'quartile': 'Q3', 'subject': 'Physics, Applied'},
         {'quartile': 'Q3', 'subject': 'Computer Science, Information Systems'}],
     'jcr_year_label': '出版方2026-09-26当前显示；分区年度未单列',
     'jcr_basis': 'MDPI统计页全部JCR学科；未以CiteScore代替',
     'sources': ['https://www.mdpi.com/journal/electronics/stats',
                 'https://www.letpub.com.cn/index.php?page=journalapp&view=search&searchname=Electronics',
                 'https://www.letpub.com.cn/index.php?journalid=10444&page=journalapp&view=detail']},
    {'journal': 'International Journal of Applied Earth Observation and Geoinformation', 'issn': '0303-2434',
     'indexing': 'SCIE', 'if_value': 8.2, 'if_year': 2025, 'if_release_year': 2026,
     'if_year_basis': 'LetPub公开页2026年6月最新IF更新口径', 'cas': '地球科学大类1区', 'cas_year': 2025,
     'provenance': 'LetPub公开汇总；非JCR或中科院官方直接查询',
     'jcr_failure': 'LetPub的JCR字段要求登录；出版方页面未取得可核验分区',
     'sources': ['https://www.letpub.com.cn/index.php?page=journalapp&view=search&searchname=International+Journal+of+Applied+Earth+Observation+and+Geoinformation',
                 'https://www.letpub.com.cn/index.php?journalid=3661&page=journalapp&view=detail']},
]
for entry in values:
    entry['checked_at'] = '2026-09-26'
    key = normalize(entry['journal'])
    registry[key] = merge_metrics(registry.get(key, {}), entry)
REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Recorded independently verified IF, CAS and subject-specific JCR evidence for three journals.')
