/** Deploy Studio UI helpers: stack presets, backing services and health badge styling. */

import type { BackingServiceId, DeployStackId } from '../types/deploy';

export interface DeployStackOption {
  id: DeployStackId;
  label: string;
  short: string;
  defaultPort: number;
  healthPath: string;
}

export const DEPLOY_STACK_OPTIONS: DeployStackOption[] = [
  {
    id: 'spring-boot',
    label: 'Spring Boot (Java 21)',
    short: 'Spring',
    defaultPort: 8080,
    healthPath: '/actuator/health',
  },
  {
    id: 'nodejs',
    label: 'Node.js (TypeScript)',
    short: 'Node',
    defaultPort: 3000,
    healthPath: '/health',
  },
  {
    id: 'csharp-dotnet',
    label: 'C# / .NET 8',
    short: '.NET',
    defaultPort: 8080,
    healthPath: '/health',
  },
  {
    id: 'csharp-wpf',
    label: 'C# WPF (desktop)',
    short: 'WPF',
    defaultPort: 8080,
    healthPath: '/health',
  },
];

export const BACKING_SERVICE_OPTIONS: Array<{ id: BackingServiceId; label: string; hint: string }> = [
  { id: 'postgres', label: 'PostgreSQL', hint: 'postgres:16-alpine + healthcheck' },
  { id: 'redis', label: 'Redis', hint: 'redis:7-alpine + AOF' },
  { id: 'rabbitmq', label: 'RabbitMQ', hint: 'rabbitmq:3.13-alpine + ping' },
];

export function stackOption(id: DeployStackId): DeployStackOption {
  return DEPLOY_STACK_OPTIONS.find((entry) => entry.id === id) ?? DEPLOY_STACK_OPTIONS[0];
}

/** Map Core IR stacks (`spring-boot`, `nodejs`, `csharp-dotnet`) to the Deploy Studio default. */
export function detectedDeployStack(detectedStacks: string[]): DeployStackId | 'auto' {
  const candidate = detectedStacks.find((stack) =>
    DEPLOY_STACK_OPTIONS.some((option) => option.id === stack),
  );
  return (candidate as DeployStackId | undefined) ?? 'auto';
}

export type HealthTone = 'healthy' | 'starting' | 'unhealthy' | 'idle';

export function containerTone(health: string, state: string): HealthTone {
  const normalized = health.toLowerCase();
  const stateText = state.toLowerCase();
  if (normalized === 'healthy') {
    return 'healthy';
  }
  if (normalized === 'starting') {
    return 'starting';
  }
  if (normalized === 'unhealthy') {
    return 'unhealthy';
  }
  if (stateText === 'running') {
    return 'healthy';
  }
  if (stateText === 'restarting' || stateText === 'created') {
    return 'starting';
  }
  return 'idle';
}

export const HEALTH_TONE_CLASS: Record<HealthTone, string> = {
  healthy: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200',
  starting: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
  unhealthy: 'border-rose-400/40 bg-rose-400/10 text-rose-200',
  idle: 'border-ink-600 bg-ink-850 text-slate-400',
};
