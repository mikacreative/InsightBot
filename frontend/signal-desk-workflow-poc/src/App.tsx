import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow, Background, BackgroundVariant, Controls, Handle, Position,
  applyNodeChanges, applyEdgeChanges, ConnectionLineType, MarkerType, useUpdateNodeInternals,
} from '@xyflow/react';
import type { Connection, Edge, EdgeChange, Node, NodeChange, NodeProps, ReactFlowInstance } from '@xyflow/react';
import type { ModuleDescriptor, Plan, PlanNode, Run, Schedule, WorkspaceState } from './types';

const activeStates = new Set(['CREATED', 'QUEUED', 'RUNNING', 'RESTARTED', 'RETRYING']);
const stateLabels: Record<string, string> = {
  CREATED: '等待开始', QUEUED: '等待开始', RUNNING: '研究进行中', PAUSED: '等待你审阅',
  SUCCESS: '已完成', FAILED: '执行失败', KILLED: '已停止', CANCELLED: '已取消',
  WARNING: '需要检查', RESTARTED: '继续执行中', SKIPPED: '未执行', PENDING: '待开始',
  COMPLETED: '已完成', REJECTED: '未发布', APPROVED: '审阅通过',
};
const kinds: Record<string, string> = {
  source: '数据来源', data_source: '数据来源', method: '研究方法', methodology: '研究方法',
  review: '人工审阅', publish: '发布渠道', publication: '发布渠道', output: '研究产出',
};
const channelNames: Record<string, string> = {
  workbench: '工作台（模拟）', wecom_simulated: '企业微信（模拟）', feishu_simulated: '飞书（模拟）',
};
const fieldLabels: Record<string, string> = {
  name: '对照品牌', competitors: '对照品牌', keywords: '关键词', focus: '分析重点', channel: '发布到',
  max_items: '最多收集条数', title: '报告标题', audience: '面向人群',
};

function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, string> = {
    folder: 'M3 7V5h6l2 2h10v12H3Z', task: 'M6 3h8l4 4v14H6Z M14 3v5h4 M9 12h6 M9 16h6',
    source: 'M5 5h14v14H5Z M8 9h8 M8 13h8 M8 17h5', method: 'M5 20V9 M12 20V4 M19 20V12',
    review: 'M4 5h16v14H4Z M8 12l3 3 5-6', publish: 'M3 11l18-8-7 18-3-7-8-3Z M11 14l10-11',
    chat: 'M20 11a7 7 0 0 1-7 7H6l-4 3 1-6a7 7 0 1 1 17-4Z',
    arrow: 'M5 12h14 M13 6l6 6-6 6', menu: 'M4 6h16 M4 12h16 M4 18h16',
    refresh: 'M19 6v5h-5 M5 18v-5h5 M19 11a7 7 0 0 0-12-6 M5 13a7 7 0 0 0 12 6',
    clock: 'M12 8v5l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={paths[name] || paths.task} />
  </svg>;
}

function kindOf(module?: ModuleDescriptor, moduleId = '') {
  return module?.kind || module?.category || moduleId.split('.')[0];
}

type FlowData = {
  label: string; description: string; kind: string; subtitle: string; status?: string; vertical: boolean;
  [key: string]: unknown;
};
type FlowNode = Node<FlowData, 'research'>;

function ResearchNode({ id, data, selected }: NodeProps<FlowNode>) {
  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    const frame = requestAnimationFrame(() => updateNodeInternals(id));
    return () => cancelAnimationFrame(frame);
  }, [id, data.vertical, data.label, data.subtitle, data.status, updateNodeInternals]);
  const icon = ['source', 'method', 'review', 'publish'].includes(data.kind) ? data.kind : 'task';
  return <div className={`research-node ${selected ? 'selected' : ''} ${data.status === 'RUNNING' ? 'running' : ''}`}>
    <Handle type="target" position={data.vertical ? Position.Top : Position.Left} aria-label={`${data.label}的输入`} />
    <div className={`node-icon node-kind-${data.kind}`}><Icon name={icon} size={24} /></div>
    <div className="node-copy"><small>{kinds[data.kind] || '研究步骤'}</small><strong title={data.label}>{data.label}</strong>
      <span title={data.subtitle || data.description}>{data.subtitle || data.description}</span>
      {data.status && <em>{stateLabels[data.status] || '执行记录已更新'}</em>}
    </div>
    <Handle type="source" position={data.vertical ? Position.Bottom : Position.Right} aria-label={`${data.label}的输出`} />
  </div>;
}
const nodeTypes = { research: ResearchNode };

function subtitle(node: PlanNode) {
  const cfg = node.config || {};
  if (typeof cfg.channel === 'string') return channelNames[cfg.channel] || '模拟发布';
  if (Array.isArray(cfg.keywords)) return cfg.keywords.join(' · ');
  if (typeof cfg.name === 'string') return cfg.name;
  if (typeof cfg.focus === 'string') return cfg.focus;
  return '';
}

function graphNodes(plan: Plan, modules: ModuleDescriptor[], run?: Run): FlowNode[] {
  const stages = run?.plan_version === plan.version ? run.steps || [] : [];
  const xs = plan.nodes.map(node => node.position.x);
  const ys = plan.nodes.map(node => node.position.y);
  const vertical = Math.max(...ys) - Math.min(...ys) > Math.max(...xs) - Math.min(...xs);
  return plan.nodes.map(node => {
    const module = modules.find(item => item.id === node.module);
    let status = stages.find(step => step.node_id === node.id)?.status;
    if (node.module === 'review.human' && run?.plan_version === plan.version) {
      status = reviewStatus(status, run);
    }
    return { id: node.id, type: 'research', position: node.position, deletable: false,
      data: { label: node.label, description: module?.description || '', kind: kindOf(module, node.module),
        subtitle: subtitle(node), status, vertical },
    };
  });
}

function reviewStatus(status: string | undefined, run: Run) {
  if (run.state === 'PAUSED') return 'PAUSED';
  if (typeof run.decision?.approved === 'boolean') return run.decision.approved ? 'APPROVED' : 'REJECTED';
  return status;
}

function graphEdges(plan: Plan): Edge[] {
  return plan.edges.map(edge => ({ ...edge, type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, width: 17, height: 17, color: '#739a98' },
    style: { stroke: '#739a98', strokeWidth: 1.7 },
  }));
}

function arrangePlan(plan: Plan): Plan {
  const ranks = new Map<string, number>();
  const remaining = new Set(plan.nodes.map(node => node.id));
  while (remaining.size) {
    let advanced = false;
    for (const id of remaining) {
      const parents = plan.edges.filter(edge => edge.target === id).map(edge => edge.source);
      if (parents.every(parent => ranks.has(parent))) {
        ranks.set(id, parents.length ? Math.max(...parents.map(parent => ranks.get(parent)!)) + 1 : 0);
        remaining.delete(id); advanced = true;
      }
    }
    if (!advanced) return plan;
  }
  const levels = new Map<number, string[]>();
  for (const node of plan.nodes) {
    const rank = ranks.get(node.id)!;
    levels.set(rank, [...(levels.get(rank) || []), node.id]);
  }
  const columns = Math.max(...[...levels.values()].map(level => level.length));
  return { ...plan, nodes: plan.nodes.map(node => {
    const rank = ranks.get(node.id)!;
    const level = levels.get(rank)!;
    return { ...node, position: { x: ((columns - level.length) / 2 + level.indexOf(node.id)) * 280, y: rank * 150 } };
  }) };
}

function formatDate(value: string | undefined) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date);
}

function errorText(cause: unknown, fallback: string) {
  if (cause instanceof TypeError) return '无法连接本机原型服务，请刷新工作台后重试。';
  if (cause instanceof SyntaxError) return '本机服务返回的数据不完整，请刷新工作台。';
  return cause instanceof Error ? cause.message : fallback;
}

function localDateTime(iso: string | null | undefined) {
  const date = iso ? new Date(iso) : new Date(Date.now() + 120_000);
  if (Number.isNaN(date.getTime())) return '';
  return new Date(date.getTime() + 8 * 3_600_000).toISOString().slice(0, 16);
}

function Markdown({ text }: { text: string }) {
  return <div className="draft-markdown">{text.split('\n').map((line, index) => {
    if (line.startsWith('### ')) return <h4 key={index}>{line.slice(4)}</h4>;
    if (line.startsWith('## ')) return <h3 key={index}>{line.slice(3)}</h3>;
    if (line.startsWith('# ')) return <h3 key={index}>{line.slice(2)}</h3>;
    if (/^[-*] /.test(line)) return <p className="draft-bullet" key={index}>{line.slice(2)}</p>;
    return line.trim() ? <p key={index}>{line}</p> : null;
  })}</div>;
}

function Inspector({ node, module, busy, onSave }: {
  node: PlanNode; module?: ModuleDescriptor; busy: boolean; onSave: (config: Record<string, unknown>) => Promise<boolean>;
}) {
  const [config, setConfig] = useState<Record<string, unknown>>(node.config);
  const [arrayText, setArrayText] = useState<Record<string, string>>(() => Object.fromEntries(
    Object.entries(node.config).filter(([, value]) => Array.isArray(value)).map(([key, value]) => [key, (value as string[]).join('，')]),
  ));
  const fields = module?.config_fields ? module.config_fields.map(field => field.key)
    : Array.isArray(module?.editable) ? module.editable : Object.keys(module?.editable || {});
  const visibleFields = (fields.length ? fields : Object.keys(node.config)).filter(key => key in fieldLabels);
  const setValue = (key: string, value: unknown) => setConfig(previous => ({ ...previous, [key]: value }));
  return <section className="card inspector" aria-label="节点设置">
    <div className="section-heading"><div><span className="eyebrow">{kinds[kindOf(module, node.module)] || '研究步骤'}</span>
      <h2>{node.label}</h2></div></div>
    <p className="help-text">{module?.description || '这是当前研究计划中的一个步骤。'}</p>
    <form onSubmit={async event => { event.preventDefault(); await onSave(config); }}>
      <div className="config-fields">{visibleFields.map(key => <label key={key}>{fieldLabels[key]}
        {key === 'channel' ? <select value={String(config[key] || 'workbench')} disabled={busy}
          onChange={event => setValue(key, event.target.value)}>
          {Object.entries(channelNames).map(([value, name]) => <option value={value} key={value}>{name}</option>)}
        </select> : key === 'keywords' || key === 'competitors' ? <input value={arrayText[key] || ''}
          placeholder="用逗号分隔" disabled={busy} onChange={event => {
            const text = event.target.value;
            setArrayText(previous => ({ ...previous, [key]: text }));
            setValue(key, text.split(/[,，\n]/).map(word => word.trim()).filter(Boolean));
          }} />
          : typeof config[key] === 'number' ? <input type="number" min="1" max="100" value={Number(config[key])}
            disabled={busy} onChange={event => setValue(key, Number(event.target.value))} />
          : <input value={String(config[key] || '')} disabled={busy} maxLength={key === 'focus' ? 1000 : 400}
            onChange={event => setValue(key, event.target.value)} />}
      </label>)}</div>
      {visibleFields.length > 0 ? <div className="card-actions"><button type="submit" className="secondary" disabled={busy}>保存这一步</button></div>
        : <p className="help-text">{kindOf(module, node.module) === 'review'
          ? '研究完成后会停在这里。你可以审阅并批准模拟发布，也可以选择不发布。'
          : '可在右侧对话中修改研究要求；执行记录会展示这一步的结果。'}</p>}
    </form>
  </section>;
}

function SchedulePanel({ schedule, status, busy, onSave }: {
  schedule: Schedule; status?: 'active' | 'paused' | 'unknown' | 'done'; busy: boolean; onSave: (schedule: Schedule) => Promise<boolean>;
}) {
  const [mode, setMode] = useState(schedule.mode || 'once');
  const [at, setAt] = useState(localDateTime(schedule.at));
  const [time, setTime] = useState(schedule.time || '09:00');
  const [weekdays, setWeekdays] = useState(schedule.weekdays || [1]);
  const weekNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
  function proposed(enabled: boolean): Schedule {
    return { enabled, mode, at: mode === 'once' && at ? new Date(`${at}:00+08:00`).toISOString() : null,
      time, weekdays, timezone: 'Asia/Shanghai' };
  }
  return <section className="card schedule-panel" aria-label="自动执行时间">
    <div className="section-heading"><h2><Icon name="clock" />自动执行</h2>
      <span className={`status ${status === 'unknown' ? '' : schedule.enabled ? 'positive' : ''}`}>{status === 'done' ? '本次已执行' : status === 'unknown' ? '待核对' : schedule.enabled ? '已开启' : '未开启'}</span>
    </div>
    <p className="help-text">按设定时间开始研究，完成后等待你审阅。时间均为北京时间。</p>
    {status === 'done' && <p className="schedule-current">本次单次安排已开始执行，结果请在“执行与审阅”查看。</p>}
    {status === 'unknown' && <p className="engine-notice" role="status">时间设置结果待核对。请先核对并关闭自动执行，再确认新的时间安排。</p>}
    <form onSubmit={async event => { event.preventDefault(); await onSave(proposed(true)); }}>
      <div className="schedule-fields"><label>频率<select value={mode} onChange={event => setMode(event.target.value as Schedule['mode'])} disabled={busy}>
        <option value="once">只执行一次</option><option value="daily">每天</option><option value="weekly">每周</option>
      </select></label>
        {mode === 'once' ? <label>执行时间<input type="datetime-local" value={at} required disabled={busy}
          onChange={event => setAt(event.target.value)} /></label>
          : <label>几点开始<input type="time" value={time} required disabled={busy} onChange={event => setTime(event.target.value)} /></label>}
      </div>
      {mode === 'weekly' && <fieldset className="weekdays"><legend>执行日</legend>{weekNames.map((day, index) =>
        <label key={day}><input type="checkbox" checked={weekdays.includes(index + 1)} disabled={busy}
          onChange={event => setWeekdays(previous => event.target.checked ? [...previous, index + 1].sort() : previous.filter(value => value !== index + 1))} />{day}</label>)}</fieldset>}
      {schedule.enabled && <p className="schedule-current">当前安排：{schedule.mode === 'once' ? formatDate(schedule.at || undefined)
        : `${schedule.mode === 'daily' ? '每天' : (schedule.weekdays || []).map(day => weekNames[day - 1]).join('、')} ${schedule.time}`}</p>}
      <div className="card-actions"><button type="submit" disabled={busy || status === 'unknown' || (mode === 'weekly' && !weekdays.length)}>保存并开启</button>
        {(schedule.enabled || status === 'unknown') && <button type="button" className="secondary" disabled={busy}
          onClick={() => void onSave({ ...schedule, enabled: false })}>{status === 'unknown' ? '核对并关闭自动执行' : '关闭自动执行'}</button>}
      </div>
    </form>
  </section>;
}

function ExecutionPanel({ runs, busy, onReview }: {
  runs: Run[]; busy: boolean; onReview: (run: Run, approved: boolean) => Promise<boolean>;
}) {
  if (!runs.length) return <div className="empty-records"><Icon name="task" size={30} /><h2>还没有执行记录</h2>
    <p>立即开始研究，或设定自动执行时间。完成后，审阅稿会出现在这里。</p></div>;
  return <div className="execution-list">{runs.map((run, index) => <section className="card execution-card" key={run.id}>
    <div className="section-heading"><div><span className="eyebrow">{formatDate(run.created_at)} · 方案 v{run.plan_version}</span>
      <h2>{index === 0 ? '最近一次研究' : '研究记录'}</h2></div>
      <span className={`status ${run.state === 'FAILED' ? 'negative' : run.state === 'SUCCESS' ? 'positive' : ''}`}>{stateLabels[run.state] || '执行状态待检查'}</span>
    </div>
    {run.error && <p className="inline-error" role="alert">{run.error}</p>}
    <ol className="step-list">{(run.steps || []).map(step => {
      const status = step.node_id === 'review' || step.module === 'review.human' ? reviewStatus(step.status, run) : step.status;
      return <li key={step.node_id}>
        <span className={`step-dot ${status === 'SUCCESS' || status === 'COMPLETED' || status === 'APPROVED' ? 'done' : ''}`} />
        <span>{step.label}</span><small>{stateLabels[status || ''] || '待开始'}</small>
      </li>;
    })}</ol>
    {run.draft && <div className="review-draft"><div className="draft-heading"><h3>研究审阅稿</h3><span>虚构示例材料</span></div>
      <Markdown text={run.draft.markdown} />
      {run.state === 'PAUSED' && <div className="review-actions"><p>这次执行采用方案 v{run.plan_version}。批准后只写入模拟发布记录。</p>
        <div><button disabled={busy || !run.draft.review_digest || run.decision?.approved === false} onClick={() => void onReview(run, true)}>批准模拟发布</button>
          <button className="secondary" disabled={busy || !run.draft.review_digest || run.decision?.approved === true} onClick={() => void onReview(run, false)}>不发布</button></div>
      </div>}
    </div>}
    {run.state === 'PAUSED' && !run.draft && <p className="help-text">执行已停下等待审阅，审阅稿暂未返回。请刷新执行记录。</p>}
    {run.publication && <div className="publication-record"><Icon name="review" />
      <div><strong>{run.publication.status === 'rejected' || run.publication.status === 'REJECTED' ? '已记录：不发布' : '模拟发布记录已保存'}</strong>
        <p>{channelNames[String(run.publication.channel || '')] || '原型工作台'} · 未向外部发送</p>
      </div></div>}
    {run.decision?.approved === false && <div className="publication-record"><Icon name="review" /><div>
      <strong>已记录：不发布</strong><p>保留研究结果，未执行模拟发布。</p>
    </div></div>}
  </section>)}</div>;
}

export default function App() {
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<'plan' | 'runs'>('plan');
  const [mobilePane, setMobilePane] = useState<'plan' | 'chat'>('plan');
  const [railOpen, setRailOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState('');
  const [selectedEdge, setSelectedEdge] = useState('');
  const [nodes, setNodes] = useState<FlowNode[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [input, setInput] = useState('');
  const [question, setQuestion] = useState('');
  const stateRef = useRef<WorkspaceState | null>(null);
  const busyRef = useRef(false);
  const messageEnd = useRef<HTMLDivElement>(null);
  const questionRef = useRef('');
  const dragRef = useRef(false);
  const flowRef = useRef<ReactFlowInstance<FlowNode, Edge> | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const inspectorRef = useRef<HTMLDivElement>(null);
  const initialLayoutChecked = useRef(false);
  const previousNodeIds = useRef<string[]>([]);
  const mutationGeneration = useRef(0);
  const readSequence = useRef(0);
  const errorKind = useRef<'read' | 'mutation' | null>(null);
  const uiBusy = busy || !!state?.planning;

  const sortedRuns = useMemo(() => [...(state?.runs || [])].sort((a, b) => b.created_at.localeCompare(a.created_at)), [state?.runs]);
  const latestRun = sortedRuns[0];
  const polling = !!state && (!state.engine.available || !!state.planning
    || (state.plan.schedule.enabled && state.schedule_status !== 'done') || state.runs.some(run => activeStates.has(run.state)));
  const topology = state ? `${state.plan.nodes.map(node => node.id).join(',')}|${state.plan.edges.map(edge => `${edge.source}>${edge.target}`).join(',')}` : '';

  const accept = useCallback((next: Partial<WorkspaceState>) => {
    setState(previous => {
      const merged = { ...previous, ...next } as WorkspaceState;
      stateRef.current = merged;
      return merged;
    });
  }, []);

  const readError = useCallback((cause: unknown, fallback: string) => {
    if (errorKind.current !== 'mutation') {
      errorKind.current = 'read'; setError(errorText(cause, fallback));
    }
  }, []);

  const refresh = useCallback(async (_initial = false) => {
    const generation = mutationGeneration.current;
    const sequence = ++readSequence.current;
    const response = await fetch('/api/state', { credentials: 'same-origin', cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '无法加载工作台，请稍后重试。');
    if (!data.plan || !data.csrf || !Array.isArray(data.plan.nodes) || !Array.isArray(data.modules)) {
      throw new Error('工作台数据不完整，请检查原型服务。');
    }
    if (!busyRef.current && generation === mutationGeneration.current && sequence === readSequence.current
      && (!stateRef.current || data.plan.version >= stateRef.current.plan.version)) accept(data);
    if (errorKind.current === 'read') { errorKind.current = null; setError(''); }
  }, [accept]);

  useEffect(() => {
    void refresh(true).catch(cause => readError(cause, '无法加载工作台。'));
  }, [refresh, readError]);

  useEffect(() => {
    if (!polling) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      let delay = stateRef.current?.engine.available ? 2000 : 10000;
      if (!busyRef.current && !dragRef.current) {
        try { await refresh(); } catch (cause) {
          if (!stopped) readError(cause, '执行记录暂时无法更新。');
          delay = 10000;
        }
      }
      if (!stopped) timer = setTimeout(poll, delay);
    };
    timer = setTimeout(poll, 2000);
    return () => { stopped = true; clearTimeout(timer); };
  }, [polling, refresh, readError]);

  useEffect(() => {
    if (!state || dragRef.current) return;
    setNodes(previous => graphNodes(state.plan, state.modules, latestRun).map(node => ({
      ...node, selected: previous.some(item => item.id === node.id && item.selected),
    })));
    setEdges(graphEdges(state.plan));
    if (!state.plan.nodes.some(node => node.id === selectedNode)) setSelectedNode(state.plan.nodes[0]?.id || '');
    if (questionRef.current !== state.plan.question) {
      setQuestion(state.plan.question); questionRef.current = state.plan.question;
    }
  }, [state, latestRun, selectedNode]);

  useEffect(() => { messageEnd.current?.scrollIntoView({ block: 'nearest', behavior: 'auto' }); }, [state?.messages.length, mobilePane]);
  useEffect(() => {
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => {
      if (tab === 'plan' && mobilePane === 'plan') void flowRef.current?.fitView({ padding: 0.13, maxZoom: 1, duration: 0 });
    }));
    return () => cancelAnimationFrame(frame);
  }, [topology, tab, mobilePane]);

  const loaded = !!state;
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let frame = 0;
    const observer = new ResizeObserver(entries => {
      if (!entries.some(entry => entry.contentRect.width > 0 && entry.contentRect.height > 0)) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => void flowRef.current?.fitView({ padding: 0.13, maxZoom: 1, duration: 0 }));
    });
    observer.observe(canvas);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [loaded, tab, mobilePane]);

  const restoreGraph = useCallback(() => {
    const current = stateRef.current;
    if (current) { setNodes(graphNodes(current.plan, current.modules)); setEdges(graphEdges(current.plan)); }
  }, []);

  const mutate = useCallback(async (path: string, payload: Record<string, unknown>, successText = ''): Promise<boolean> => {
    if (busyRef.current || !stateRef.current || stateRef.current.planning) return false;
    mutationGeneration.current += 1;
    errorKind.current = null;
    busyRef.current = true; setBusy(true); setError(''); setNotice('');
    try {
      const response = await fetch(path, { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Signal-Desk-CSRF': stateRef.current.csrf }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 409) {
          busyRef.current = false; await refresh();
          throw new Error(data.error || '方案已有更新，已加载最新版本。请重新提交修改。');
        }
        throw new Error(data.error || '修改未保存，请重试。');
      }
      if (data.plan || data.runs || data.messages || data.engine) accept(data);
      busyRef.current = false;
      try { await refresh(); } catch (cause) {
        errorKind.current = 'read';
        setError(`修改已提交，执行记录暂时无法更新。${errorText(cause, '请刷新工作台确认。')}`);
        return true;
      }
      setNotice(data.planning ? '正在制定研究计划，完成后会同步到流程图。'
        : path === '/api/schedule' && data.schedule_status === 'unknown' ? '时间设置结果待核对，请查看自动执行卡片。' : successText);
      return true;
    } catch (cause) {
      errorKind.current = 'mutation';
      setError(errorText(cause, '请求失败，请刷新后确认修改状态。'));
      restoreGraph();
      return false;
    } finally { busyRef.current = false; setBusy(false); }
  }, [accept, refresh, restoreGraph]);

  const savePlan = useCallback(async (plan: Plan, successText = '方案已保存。'): Promise<boolean> => {
    const current = stateRef.current;
    if (!current) return false;
    return mutate('/api/plan', { plan, expected_version: current.plan.version }, successText);
  }, [mutate]);

  useEffect(() => {
    if (!state || state.planning || busyRef.current || dragRef.current) return;
    const ids = state.plan.nodes.map(node => node.id);
    const addedNodes = previousNodeIds.current.length > 0 && ids.some(id => !previousNodeIds.current.includes(id));
    const xs = state.plan.nodes.map(node => node.position.x);
    const ys = state.plan.nodes.map(node => node.position.y);
    const initialHorizontal = !initialLayoutChecked.current && Math.max(...xs) - Math.min(...xs) > 700
      && Math.max(...xs) - Math.min(...xs) > Math.max(...ys) - Math.min(...ys);
    initialLayoutChecked.current = true;
    previousNodeIds.current = ids;
    if (initialHorizontal || addedNodes) {
      const arranged = arrangePlan(state.plan);
      setNodes(graphNodes(arranged, state.modules, latestRun));
      void savePlan(arranged, '').then(saved => {
        if (saved) setTimeout(() => void flowRef.current?.fitView({ padding: 0.13, maxZoom: 1, duration: 0 }), 0);
      });
    }
  }, [state, latestRun, savePlan]);

  const onConnect = useCallback((connection: Connection) => {
    const current = stateRef.current;
    if (!current || current.planning || busyRef.current || !connection.source || !connection.target) return;
    if (connection.source === connection.target) { errorKind.current = 'mutation'; setError('不能把一个步骤连接到自己。'); return; }
    if (current.plan.edges.some(edge => edge.source === connection.source && edge.target === connection.target)) return;
    const plan = { ...current.plan, edges: [...current.plan.edges, {
      id: `edge_${crypto.randomUUID().replaceAll('-', '')}`, source: connection.source, target: connection.target,
    }] };
    setEdges(graphEdges(plan));
    void savePlan(plan, '连线已保存。');
  }, [savePlan]);

  const removeEdges = useCallback((ids: string[]) => {
    const current = stateRef.current;
    if (!current || current.planning || busyRef.current) return;
    const plan = { ...current.plan, edges: current.plan.edges.filter(edge => !ids.includes(edge.id)) };
    setEdges(graphEdges(plan)); setSelectedEdge('');
    void savePlan(plan, '连线已移除。');
  }, [savePlan]);

  const reconnect = useCallback((oldEdge: Edge, connection: Connection) => {
    const current = stateRef.current;
    if (!current || current.planning || busyRef.current || !connection.source || !connection.target) return;
    const plan = { ...current.plan, edges: current.plan.edges.map(edge => edge.id === oldEdge.id
      ? { ...edge, source: connection.source!, target: connection.target! } : edge) };
    setEdges(graphEdges(plan));
    void savePlan(plan, '连线已调整。');
  }, [savePlan]);

  function changeEdges(changes: EdgeChange[]) {
    const removed = changes.filter(change => change.type === 'remove').map(change => change.id);
    setEdges(previous => applyEdgeChanges(changes, previous));
    if (removed.length) removeEdges(removed);
  }

  function changeNodes(changes: NodeChange<FlowNode>[]) {
    setNodes(previous => applyNodeChanges(changes.filter(change => change.type !== 'remove'), previous));
  }

  async function sendChat(message: string) {
    const current = stateRef.current;
    if (!message.trim() || !current) return;
    const saved = await mutate('/api/chat', { message: message.trim(), expected_version: current.plan.version,
      request_id: crypto.randomUUID() }, '方案已根据对话更新。');
    if (saved) setInput('');
  }

  const chosenNode = state?.plan.nodes.find(node => node.id === selectedNode);
  const chosenModule = state?.modules.find(module => module.id === chosenNode?.module);
  const running = state?.runs.some(run => activeStates.has(run.state));
  const pendingReview = sortedRuns.some(run => run.state === 'PAUSED');
  const planVersion = state?.plan.version;
  const scheduleLabel = state?.schedule_status === 'unknown' ? '自动执行待核对'
    : state?.schedule_status === 'done' ? '本次定时研究已执行'
    : state?.plan.schedule.enabled ? '自动执行已开启' : '自动执行未开启';

  return <div className="app">
    <header className="app-header"><button className="icon-button rail-toggle" aria-label="打开品牌任务栏" onClick={() => setRailOpen(!railOpen)}><Icon name="menu" /></button>
      <span className="wordmark">Signal Desk<span className="wordmark-dot" /></span>
      <span className="prototype-badge">本机原型</span><p className="prototype-note">虚构数据 · 模拟发布</p>
      <button className="icon-button refresh-button" title="刷新工作台" aria-label="刷新工作台" disabled={uiBusy}
        onClick={() => void refresh().then(() => { errorKind.current = null; setError(''); setNotice('执行记录已更新。'); }).catch(cause => readError(cause, '执行记录暂时无法更新。'))}><Icon name="refresh" /></button>
    </header>
    {(error || notice) && <div className={`feedback ${error ? 'error' : ''}`} role={error ? 'alert' : 'status'}>
      <span>{error || notice}</span><button className="icon-button" aria-label="关闭提示" onClick={() => { errorKind.current = null; setError(''); setNotice(''); }}>×</button>
    </div>}
    {!state ? <main className="loading-screen"><Icon name="task" size={36} /><h1>{error ? '工作台暂时无法加载' : '正在加载研究工作台…'}</h1>
      <p>{error || '连接本机原型服务。'}</p>{error && <button onClick={() => void refresh(true).catch(cause => readError(cause, '无法加载工作台。'))}>重新加载</button>}</main>
      : <div className={`workspace ${railOpen ? 'rail-open' : ''} mobile-${mobilePane}`}>
        {railOpen && <button className="rail-scrim" aria-label="关闭任务栏" onClick={() => setRailOpen(false)} />}
        <aside className="task-rail" aria-label="品牌与任务"><div className="rail-title">研究任务</div>
          <div className="brand-group"><div className="brand-name"><Icon name="folder" /><strong>{state.plan.brand.name || '澄野（虚构）'}</strong><span>1</span></div>
            <button className="task-row active" aria-current="page" onClick={() => { setRailOpen(false); setMobilePane('plan'); }}>
              <Icon name="task" /><span><strong>户外杯研究</strong><small>{running ? '研究进行中' : latestRun?.state === 'PAUSED' ? '等待审阅' : `方案 v${planVersion}`}</small></span>
            </button>
          </div>
          <div className="rail-footer"><span className={`connection-dot ${state.engine.available ? 'connected' : ''}`} /><span>{state.engine.available ? '执行服务已连接' : '执行服务未连接'}</span>
            <p>原型只使用示例材料，所有发布均为模拟。</p>
          </div>
        </aside>
        <main className="task-details"><div className="task-header"><div><span className="eyebrow">{state.plan.brand.name} / 研究任务</span><h1>户外杯研究</h1></div>
          <button disabled={uiBusy || (!pendingReview && (!state.engine.available || !!running))} onClick={async () => {
            if (pendingReview) { setTab('runs'); return; }
            const saved = await mutate('/api/execute', { request_id: crypto.randomUUID(), expected_version: state.plan.version }, '研究已开始，完成后会等待你审阅。');
            if (saved) setTab('runs');
          }}>{pendingReview ? '检阅研究结果' : running ? '研究进行中' : '立即开始研究'}<Icon name="arrow" size={17} /></button>
        </div>
          <nav className="detail-tabs" aria-label="任务详情视图"><button className={tab === 'plan' ? 'active' : ''} aria-current={tab === 'plan' ? 'page' : undefined} onClick={() => setTab('plan')}>研究计划</button>
            <button className={tab === 'runs' ? 'active' : ''} aria-current={tab === 'runs' ? 'page' : undefined} onClick={() => setTab('runs')}>执行与审阅{sortedRuns.some(run => run.state === 'PAUSED') && <span className="tab-dot" />}</button>
            <span className="version-label">{state.planning ? '正在制定方案…' : busy ? '正在保存…' : `方案 v${planVersion}`}</span>
          </nav>
          <div className="detail-scroll">{!state.engine.available && <div className="engine-notice" role="status">
            执行服务尚未连接，方案仍可检阅和修改。{state.engine.error && <details><summary>连接详情</summary><p>{state.engine.error}</p></details>}</div>}
            {tab === 'plan' ? <>
              <div className="question-card"><span className="eyebrow">本次要回答的问题</span><p>{state.plan.question}</p>
                <details><summary>手动修改问题</summary><form onSubmit={event => { event.preventDefault(); void savePlan({ ...state.plan, question }, '研究问题已保存。'); }}>
                  <label className="sr-only" htmlFor="question-input">研究问题</label><textarea id="question-input" value={question} required maxLength={1500} disabled={uiBusy} onChange={event => setQuestion(event.target.value)} />
                  <button type="submit" className="secondary" disabled={uiBusy || !question.trim()}>保存问题</button>
                </form></details>
              </div>
              <div className="canvas-shell"><div className="canvas-label"><span>研究流程</span><small>点击步骤查看设置</small>
                <button className="text-button" disabled={uiBusy} onClick={async () => {
                  if (await savePlan(arrangePlan(state.plan), '流程图布局已整理。')) {
                    setTimeout(() => void flowRef.current?.fitView({ padding: 0.13, maxZoom: 1, duration: 0 }), 0);
                  }
                }}>整理布局</button></div>
                <div className="flow-canvas" ref={canvasRef} aria-label="可拖拽的研究流程图">
                  <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={changeNodes}
                    onEdgesChange={changeEdges} onConnect={onConnect} onReconnect={reconnect} edgesReconnectable={!uiBusy}
                    connectionLineType={ConnectionLineType.Straight} zoomOnScroll={false} preventScrolling={false}
                    nodesDraggable={!uiBusy} nodesConnectable={!uiBusy} onInit={instance => { flowRef.current = instance; }}
                    elementsSelectable={!uiBusy}
                    onNodeClick={(_, node) => {
                      setSelectedNode(node.id); setSelectedEdge('');
                      requestAnimationFrame(() => inspectorRef.current?.scrollIntoView({ block: 'nearest', behavior: 'auto' }));
                    }}
                    onEdgeClick={(_, edge) => setSelectedEdge(edge.id)} onPaneClick={() => setSelectedEdge('')}
                    onNodeDragStart={() => { dragRef.current = true; }} onNodeDragStop={(_, node) => {
                      dragRef.current = false;
                      const current = stateRef.current;
                      if (!current) return;
                      void savePlan({ ...current.plan, nodes: current.plan.nodes.map(item => item.id === node.id ? { ...item, position: node.position } : item) }, '节点位置已保存。');
                    }}
                    fitView fitViewOptions={{ padding: 0.17, maxZoom: 0.95 }} minZoom={0.25} maxZoom={1.4}
                    deleteKeyCode={uiBusy ? null : ['Backspace', 'Delete']} proOptions={{ hideAttribution: true }}
                    ariaLabelConfig={{ 'controls.zoomIn.ariaLabel': '放大流程图', 'controls.zoomOut.ariaLabel': '缩小流程图', 'controls.fitView.ariaLabel': '显示全部步骤' }}>
                    <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#d3dfe3" />
                    <Controls showInteractive={false} />
                  </ReactFlow>
                </div><div className="canvas-help"><span>拖动节点或连线端点调整流程；选中连线可删除。修改会保存并核对。</span>
                  {selectedEdge && <button className="text-button" disabled={uiBusy} onClick={() => removeEdges([selectedEdge])}>移除选中连线</button>}
                </div></div>
              {chosenNode && <div ref={inspectorRef}><Inspector key={`${chosenNode.id}-${planVersion}`} node={chosenNode} module={chosenModule} busy={uiBusy}
                onSave={config => savePlan({ ...state.plan, nodes: state.plan.nodes.map(node => node.id === chosenNode.id ? { ...node, config } : node) }, '节点设置已保存。')} /></div>}
              <SchedulePanel key={`${planVersion}-${JSON.stringify(state.plan.schedule)}`} schedule={state.plan.schedule} status={state.schedule_status} busy={uiBusy}
                onSave={schedule => mutate('/api/schedule', { schedule, expected_version: state.plan.version }, schedule.enabled ? '自动执行已开启。' : '自动执行已关闭。')} />
            </> : <ExecutionPanel runs={sortedRuns} busy={uiBusy || !state.engine.available} onReview={(run, approved) => mutate('/api/review', {
              execution_id: run.id, approved, review_digest: run.draft?.review_digest,
            }, approved ? '审阅已通过，继续模拟发布。' : '已记录不发布。')} />}
          </div>
        </main>
        <aside className="conversation-panel" aria-label="通过对话修改研究计划"><div className="conversation-header"><Icon name="chat" /><h2>一起制定研究计划</h2></div>
          <div className={`planner-label ${state.planner.mode === 'demo' ? 'demo' : ''}`}>{state.planner.mode === 'demo' ? '演示对话（未连接模型）' : state.planner.label || 'AI 对话已连接'}<span> · {scheduleLabel}</span></div>
          <div className="chat-scroll"><div className="chat-intro"><h3>告诉我想研究什么</h3><p>可以补充研究重点、增加竞品对照，或调整执行时间。方案变化会同步显示在流程图中。</p>
              <div className="suggestions"><button disabled={uiBusy} onClick={() => void sendChat('增加映山（虚构）作为竞品，比较两个品牌的户外杯卖点。')}>增加竞品对照<Icon name="arrow" size={15} /></button>
                <button disabled={uiBusy} onClick={() => { setInput('把研究问题改为：消费者选择户外杯时，最在意哪些卖点？'); setMobilePane('chat'); }}>调整研究问题<Icon name="arrow" size={15} /></button></div>
            </div>
            {(state.messages || []).filter(message => message.role !== 'system').map((message, index) => <div className={`chat-message ${message.role}`} key={message.id || index}>
              <div className="message-speaker">{message.role === 'user' ? '你' : state.planner.mode === 'demo' ? '规划演示' : 'Signal Desk'}</div>
              <p>{message.content || message.text}</p>{message.plan_version && <span className="message-version">已更新为方案 v{message.plan_version}</span>}
            </div>)}
            {uiBusy && <p className="chat-working" role="status">{state.planning ? '正在制定研究计划…' : '正在处理修改…'}</p>}<div ref={messageEnd} />
          </div>
          <form className="chat-composer" onSubmit={event => { event.preventDefault(); void sendChat(input); }}><label className="sr-only" htmlFor="chat-input">输入研究要求</label>
            <div className="composer-box"><textarea id="chat-input" value={input} disabled={uiBusy} placeholder="说说你想调整什么…" rows={3} maxLength={3000}
              onChange={event => setInput(event.target.value)} onKeyDown={event => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void sendChat(input); }
              }} /><button type="submit" disabled={uiBusy || !input.trim()} aria-label="发送修改要求"><Icon name="arrow" size={20} /></button></div>
            <p>{state.planner.mode === 'demo' ? '演示仅支持指定修改；研究判断使用虚构示例。' : '发送后更新方案；开始执行和发布需要单独操作。'}</p>
          </form>
        </aside>
        <nav className="mobile-switch" aria-label="切换计划与对话"><button className={mobilePane === 'plan' ? 'active' : ''} onClick={() => setMobilePane('plan')}><Icon name="task" size={18} />计划与执行</button>
          <button className={mobilePane === 'chat' ? 'active' : ''} onClick={() => setMobilePane('chat')}><Icon name="chat" size={18} />对话修改</button></nav>
      </div>}
  </div>;
}
