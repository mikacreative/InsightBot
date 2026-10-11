"""Single source of truth for evidence grades (METHODOLOGY.md §5.2).

Every module that reads or writes ``source_grade`` goes through this module. The reason
is a real defect: until 2026-10-11 the JustOneAPI adapter emitted ``'search excerpt'``,
a token that neither ``core._excerpt_rank`` nor ``editorial_v2`` recognised. Both sites
fell through to their permissive branch, so a truncated 60-character search summary
ranked as mid-strength evidence and the "summary cannot support a claim" guard never
fired. A grade vocabulary that only some call sites know is how that happens.

Two protections follow from it:

* **One table.** Levels, ranks and the summary gate are declared once, below. Adding a
  level cannot silently opt out of a guard.
* **Unknown means weakest.** Any token not in the table (typo, new vendor field, stored
  run from an older schema) resolves to ``unverified``: rank 0, summary-only. Failing
  closed is the only safe default, because the failure mode of the opposite default is
  inflated evidence strength, which is invisible in the output.

``source_grade`` historically carried two unrelated facts in one string, joined by
``" | "``: what the text *is* and which *population* it samples. Both are still read
from that same field for compatibility with stored runs, but they are answered by
separate functions — :func:`level` and :func:`kind` — so neither axis can be mistaken
for the other again.

See ``METHODOLOGY.md`` §5.2 for the level definitions and ``docs/signal-desk/
JUSTONEAPI-ASSETS.md`` §2.8 for the migration record.
"""

# 版本号随词汇表变更递增；已落库的 run 里可能仍是旧 token，由 _ALIASES 兜住。
GRADE_VOCABULARY_VERSION = '2026-10-11.1'

# level -> (rank, summary_only, note_text)
#   rank         仅用于同一 source_id 去重时挑选"文本更深"的 excerpt：越大越优先。
#                非笔记文本的等级一律为 0 —— 它们不会与笔记文本共用同一个 source 键，
#                该值不参与任何比较。
#   summary_only True = 只有标题或截断摘要，不能单独支撑一条完整判断（编辑守卫用）。
#                注意它与 rank 是两条独立的轴：正文层的 rank 最高，但摘要层与标题层
#                同为 summary_only，只是摘要比标题多一点文本。
#   note_text    True = 该等级承载一条笔记的文本（而非结构化指标或趋势序列）
_LEVELS = {
    'note_meta': (0, True, True),        # 标题、作者、发布时间、互动指标（METHODOLOGY §2.2 标题层）
    'note_segment': (1, True, True),     # 命中片段／截断摘要：搜索 desc ≤60 字符、千瓜命中片段（§2.2 摘要层）
    'note_comment': (2, False, True),    # 评论全文与楼中楼（§2.2 评论层）
    'note_body': (3, False, True),       # 笔记正文全文，仅经 get-note-detail/v1|v6（§2.2 正文层）
    'note_structure': (0, False, False),  # 标签、话题、发布统计
    'note_linked': (0, False, False),    # 可核查原文 URL
    'brand_structure': (0, False, False),  # SOV、达人金字塔、类目漏斗、榜单（千瓜独占）
    'trend_series': (0, False, False),   # 平台级日／周时间序列（千瓜独占，PDD §7.4 唯一正当来源）
}

# 非 METHODOLOGY §5.2 等级，仅作标记用。
UNVERIFIED = 'unverified'        # 无从判定：按最弱处理
EXTERNAL_CONTEXT = 'external_context'  # 背景材料，从来不是证据（core.EDITOR_PROMPT 已定义该概念）

_MARKERS = {
    UNVERIFIED: (0, True, True),
    EXTERNAL_CONTEXT: (0, True, False),
}

# 旧 token -> 现行等级。这些值可能出现在已落库的 run、缓存与历史报告里。
# * title_only / search_snippet / rss_snippet  —— v0.2.1 之前的代码词表
# * qiangua_body                              —— 误名：METHODOLOGY §5.2 已 endpoint 级确认千瓜无正文接口，
#                                                它实际返回的是命中片段，因此归入 note_segment 而非 note_body
# * full_text                                 —— 测试与部分导入路径使用
_ALIASES = {
    'title_only': 'note_meta',
    'search_snippet': 'note_segment',
    'search excerpt': 'note_segment',   # 2026-10-11 之前的 providers.py 输出
    'qiangua_body': 'note_segment',
    'full_text': 'note_body',
    'note body': 'note_body',
    'note text': 'note_body',
    'comment thread': 'note_comment',
    'qiangua comment thread': 'note_comment',
    'rss_snippet': EXTERNAL_CONTEXT,
    'external context': EXTERNAL_CONTEXT,
    'unverified sample': UNVERIFIED,
}

KNOWN_KINDS = ('general', 'commercial')
UNCLASSIFIED = 'unclassified'


def split(grade):
    """Split ``"<level> | <kind>"`` into its two tokens.

    Returns ``(level_token, kind_token_or_None)`` without resolving aliases.
    """
    raw = str(grade or '')
    # rpartition keeps the historical reading of the kind suffix (last segment wins);
    # a level token never contains a pipe, so a malformed multi-pipe value fails closed
    # at the level rather than silently picking a middle segment.
    head, separator, tail = raw.rpartition('|')
    if not separator:
        return raw.strip(), None
    return head.strip(), tail.strip() or None


def level(grade):
    """Canonical level token. Aliases resolve; anything unrecognised becomes ``unverified``."""
    token = split(grade)[0].strip().lower()
    token = _ALIASES.get(token, token)
    if token in _LEVELS or token in _MARKERS:
        return token
    return UNVERIFIED


def kind(grade):
    """Sample population. Currently ``unclassified`` for every pipeline-produced grade —
    nothing writes the ``|kind`` suffix yet; see JUSTONEAPI-ASSETS.md §2.8."""
    token = (split(grade)[1] or '').lower()
    if 'commercial' in token:
        return 'commercial'
    return 'general' if token == 'general' else UNCLASSIFIED


def rank(grade):
    """Text depth, for choosing between snapshots of the same source. Unknown = 0."""
    return _LEVELS.get(level(grade), _MARKERS[UNVERIFIED])[0]


def summary_only(grade):
    """True when the text is a title or a truncated summary. Drives the editorial guard."""
    return _LEVELS.get(level(grade), _MARKERS[UNVERIFIED])[1]


def is_note_text(grade):
    """True when the grade carries a note's own text rather than a structural metric."""
    return _LEVELS.get(level(grade), _MARKERS[UNVERIFIED])[2]


def is_evidence(grade):
    """False only for material flagged as background rather than evidence."""
    return level(grade) != EXTERNAL_CONTEXT


def is_comment(grade):
    return level(grade) == 'note_comment'


def is_body(grade):
    """True only for a retrieved note body — never for a search summary."""
    return level(grade) == 'note_body'


def is_meta(grade):
    """True only for title-and-metadata evidence, i.e. the enrichment target."""
    return level(grade) == 'note_meta'


def canonical(grade):
    """Normalised ``"<level> | <kind>"``, or the bare level when no kind is present."""
    resolved, kind_token = level(grade), split(grade)[1]
    return f'{resolved} | {kind_token}' if kind_token else resolved


def describe(grade):
    """One-line audit string for report headers and debugging."""
    return (f'{canonical(grade)} (level={level(grade)}, rank={rank(grade)}, '
            f'summary_only={summary_only(grade)}, kind={kind(grade)})')
