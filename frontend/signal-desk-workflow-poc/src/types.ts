export interface PlanNode {
  id: string;
  module: string;
  label: string;
  position: { x: number; y: number };
  config: Record<string, unknown>;
}

export interface PlanEdge {
  id: string;
  source: string;
  target: string;
}

export interface Schedule {
  enabled: boolean;
  mode: 'once' | 'daily' | 'weekly';
  at: string | null;
  time: string;
  weekdays: number[];
  timezone: string;
}

export interface Plan {
  id: string;
  version: number;
  brand: { id: string; name: string };
  question: string;
  nodes: PlanNode[];
  edges: PlanEdge[];
  schedule: Schedule;
}

export interface ModuleDescriptor {
  id: string;
  label: string;
  description: string;
  kind?: string;
  category?: string;
  editable?: string[] | Record<string, unknown>;
  config_fields?: { key: string; label: string; type: string; options?: string[] }[];
  default_config?: Record<string, unknown>;
}

export interface Message {
  id?: string;
  role: 'user' | 'assistant' | 'system';
  content?: string;
  text?: string;
  created_at?: string;
  plan_version?: number;
}

export interface RunStep {
  node_id: string;
  module?: string;
  label: string;
  status: string;
  output?: unknown;
  completed_at?: string;
}

export interface Run {
  id: string;
  state: string;
  plan_version: number;
  created_at: string;
  steps: RunStep[];
  draft?: { markdown: string; review_digest: string };
  publication?: Record<string, unknown>;
  decision?: { approved: boolean; review_digest: string; at?: string };
  error?: string;
}

export interface WorkspaceState {
  plan: Plan;
  modules: ModuleDescriptor[];
  messages: Message[];
  runs: Run[];
  engine: { available: boolean; version?: string; error?: string };
  planner: { mode: 'ai' | 'demo'; label?: string };
  csrf: string;
  planning?: boolean | string | null;
  schedule_status?: 'active' | 'paused' | 'unknown' | 'done';
}
