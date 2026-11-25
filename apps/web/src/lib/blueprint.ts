/** Blueprint defaults, stack-aware presets and validation for the Phase 4 Builder. */

import type { Blueprint, BlueprintField, BlueprintSlice, BlueprintStack } from '../types/blueprint';

export interface StackOption {
  id: BlueprintStack;
  label: string;
  short: string;
  baseLabel: string;
  basePlaceholder: string;
  description: string;
  fieldTypes: string[];
  annotationPresets: string[];
  defaultProject: string;
  defaultBase: string;
}

export const STACK_OPTIONS: StackOption[] = [
  {
    id: 'spring-boot',
    label: 'Spring Boot',
    short: 'Java 21 · Spring Boot 3',
    baseLabel: 'Base package',
    basePlaceholder: 'com.acme.billing',
    description:
      'Entity + DTO record + Mapper + JpaRepository + Service + RestController + JUnit/Mockito test.',
    fieldTypes: [
      'string',
      'text',
      'email',
      'int',
      'long',
      'decimal',
      'boolean',
      'date',
      'datetime',
      'uuid',
    ],
    annotationPresets: [
      '@NotNull',
      '@NotBlank',
      '@Size(max = 200)',
      '@Email',
      '@Positive',
      '@Column(nullable = false)',
      '@Column(unique = true)',
    ],
    defaultProject: 'Acme Billing',
    defaultBase: 'com.acme.billing',
  },
  {
    id: 'csharp-wpf',
    label: 'C# WPF (MVVM)',
    short: '.NET 8 · WPF',
    baseLabel: 'Root namespace',
    basePlaceholder: 'Acme.Desktop',
    description:
      'Model + service interface/implementation + CommunityToolkit ViewModel + XAML view + xUnit test.',
    fieldTypes: ['string', 'text', 'email', 'int', 'long', 'decimal', 'double', 'boolean', 'date', 'datetime', 'uuid'],
    annotationPresets: [
      '[Required]',
      '[StringLength(200)]',
      '[Range(0, 999999)]',
      '[EmailAddress]',
      '[Key]',
    ],
    defaultProject: 'Acme.Desktop',
    defaultBase: 'Acme.Desktop',
  },
  {
    id: 'nodejs',
    label: 'Node.js (TS)',
    short: 'Express · TypeScript',
    baseLabel: 'Source root',
    basePlaceholder: 'src',
    description: 'Entity + class-validator DTO + repository + service + controller + Vitest spec.',
    fieldTypes: ['string', 'text', 'email', 'int', 'long', 'number', 'decimal', 'boolean', 'date', 'datetime', 'uuid'],
    annotationPresets: [
      '@IsNotEmpty()',
      '@IsString()',
      '@IsNumber()',
      '@IsEmail()',
      '@Min(0)',
      '@Max(100)',
      '@Length(1, 200)',
    ],
    defaultProject: 'acme-api',
    defaultBase: 'src',
  },
  {
    id: 'python-fastapi',
    label: 'Python (FastAPI)',
    short: 'FastAPI · Pydantic · SQLAlchemy',
    baseLabel: 'Package root',
    basePlaceholder: 'app',
    description:
      'SQLAlchemy model + Pydantic request/response + repository + service + APIRouter module + pytest skeleton.',
    fieldTypes: [
      'string',
      'text',
      'email',
      'int',
      'long',
      'decimal',
      'boolean',
      'date',
      'datetime',
      'uuid',
    ],
    annotationPresets: ['Field(min_length=1)', 'Field(ge=0)', 'Field(max_length=200)'],
    defaultProject: 'acme-api',
    defaultBase: 'app',
  },
];

export function stackOption(stack: BlueprintStack): StackOption {
  return STACK_OPTIONS.find((option) => option.id === stack) ?? STACK_OPTIONS[0];
}

export function blankField(stack: BlueprintStack): BlueprintField {
  const option = stackOption(stack);
  return { name: '', type: option.fieldTypes[0] ?? 'string', required: true, annotations: [] };
}

export function blankSlice(name: string): BlueprintSlice {
  return { name, fields: [], dependsOnSlices: [], includeTests: true };
}

export function defaultBlueprint(stack: BlueprintStack = 'spring-boot'): Blueprint {
  const option = stackOption(stack);
  return {
    schemaVersion: '1.0',
    projectName: option.defaultProject,
    stack,
    basePackageOrNamespace: option.defaultBase,
    slices: [
      {
        name: 'Invoice',
        fields: [
          { name: 'number', type: 'string', required: true, annotations: [] },
          { name: 'amount', type: 'decimal', required: true, annotations: [] },
          { name: 'dueDate', type: 'date', required: false, annotations: [] },
        ],
        dependsOnSlices: [],
        includeTests: true,
      },
    ],
  };
}

/** The 3-service demo: Customer <- Order <- Payment (no cycles). */
export function demoSlices(_stack: BlueprintStack): BlueprintSlice[] {
  return [
    {
      name: 'Customer',
      fields: [
        { name: 'fullName', type: 'string', required: true, annotations: [] },
        { name: 'email', type: 'email', required: true, annotations: [] },
      ],
      dependsOnSlices: [],
      includeTests: true,
    },
    {
      name: 'Order',
      fields: [
        { name: 'number', type: 'string', required: true, annotations: [] },
        { name: 'total', type: 'decimal', required: true, annotations: [] },
        { name: 'status', type: 'string', required: true, annotations: [] },
      ],
      dependsOnSlices: ['Customer'],
      includeTests: true,
    },
    {
      name: 'Payment',
      fields: [
        { name: 'reference', type: 'string', required: true, annotations: [] },
        { name: 'amount', type: 'decimal', required: true, annotations: [] },
        { name: 'method', type: 'string', required: true, annotations: [] },
      ],
      dependsOnSlices: ['Order'],
      includeTests: true,
    },
  ];
}

export function uniqueSliceName(slices: BlueprintSlice[]): string {
  const taken = new Set(slices.map((slice) => slice.name));
  let candidate = 'NewSlice';
  let index = 2;
  while (taken.has(candidate)) {
    candidate = `NewSlice${index}`;
    index += 1;
  }
  return candidate;
}

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;
const PASCAL = /^[A-Z][A-Za-z0-9]*$/;
const QUALIFIED = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/;

export function validateBlueprint(blueprint: Blueprint): string[] {
  const problems: string[] = [];
  const option = stackOption(blueprint.stack);

  if (!blueprint.projectName.trim()) {
    problems.push('Project name is required.');
  }
  const base = blueprint.basePackageOrNamespace.trim();
  if (!base) {
    problems.push(`${option.baseLabel} is required.`);
  } else if (blueprint.stack === 'nodejs') {
    if (!/^[A-Za-z0-9_./-]+$/.test(base)) {
      problems.push('Source root may only contain letters, digits, "_", ".", "/" or "-".');
    }
  } else if (!QUALIFIED.test(base)) {
    problems.push(
      blueprint.stack === 'csharp-wpf'
        ? 'Namespace must be dot-separated identifiers (e.g. Acme.Desktop).'
        : 'Base package must be dot-separated identifiers (e.g. com.acme.billing).',
    );
  }

  if (blueprint.slices.length === 0) {
    problems.push('Define at least one slice.');
  }

  const names = blueprint.slices.map((slice) => slice.name.trim());
  const duplicates = names.filter((name, index) => names.indexOf(name) !== index);
  if (duplicates.length > 0) {
    problems.push(`Duplicate slice name(s): ${[...new Set(duplicates)].join(', ')}.`);
  }
  const known = new Set(names);

  blueprint.slices.forEach((slice, sliceIndex) => {
    const label = slice.name.trim() || `Slice ${sliceIndex + 1}`;
    if (!PASCAL.test(slice.name.trim())) {
      problems.push(`${label}: slice names must be PascalCase (letters and digits only).`);
    }
    const fieldNames = slice.fields.map((field) => field.name.trim());
    slice.fields.forEach((field, fieldIndex) => {
      if (!IDENTIFIER.test(field.name.trim())) {
        problems.push(`${label}: field ${fieldIndex + 1} needs a valid name.`);
      }
      if (!field.type.trim()) {
        problems.push(`${label}.${field.name.trim() || fieldIndex + 1}: choose a type.`);
      }
    });
    const duplicated = fieldNames.filter((name, index) => name && fieldNames.indexOf(name) !== index);
    if (duplicated.length > 0) {
      problems.push(`${label}: duplicate field name(s) ${[...new Set(duplicated)].join(', ')}.`);
    }
    slice.dependsOnSlices.forEach((dependency) => {
      if (!known.has(dependency)) {
        problems.push(`${label}: depends on unknown slice ${dependency}.`);
      }
    });
  });

  return problems;
}

export function sliceDependencyChoices(
  slices: BlueprintSlice[],
  activeIndex: number,
): Array<{ name: string; selected: boolean }> {
  const active = slices[activeIndex];
  if (!active) {
    return [];
  }
  return slices
    .filter((_, index) => index !== activeIndex)
    .map((slice) => ({ name: slice.name, selected: active.dependsOnSlices.includes(slice.name) }));
}
