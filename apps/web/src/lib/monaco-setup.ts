import { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker';
import cssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker';
import htmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker';
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker';

// Bundle Monaco locally (no CDN) so the desktop build works fully offline.
window.MonacoEnvironment = {
  getWorker(_moduleId: string, label: string) {
    if (label === 'json') return new jsonWorker();
    if (label === 'css' || label === 'scss' || label === 'less') return new cssWorker();
    if (label === 'html' || label === 'handlebars' || label === 'razor') return new htmlWorker();
    if (label === 'typescript' || label === 'javascript') return new tsWorker();
    return new editorWorker();
  },
};

loader.config({ monaco });

monaco.editor.defineTheme('kodo-dark', {
  base: 'vs-dark',
  inherit: true,
  rules: [
    { token: 'comment', foreground: '5b6b82', fontStyle: 'italic' },
    { token: 'keyword', foreground: '7dd3fc' },
    { token: 'string', foreground: '86efac' },
    { token: 'number', foreground: 'fbbf24' },
    { token: 'type', foreground: 'c4b5fd' },
  ],
  colors: {
    'editor.background': '#0b0f16',
    'editor.foreground': '#dbe4f0',
    'editorLineNumber.foreground': '#31405a',
    'editorLineNumber.activeForeground': '#7d8fae',
    'editor.selectionBackground': '#1e3a5f',
    'editor.lineHighlightBackground': '#0f1621',
    'editorCursor.foreground': '#38bdf8',
    'editorGutter.background': '#0b0f16',
  },
});
