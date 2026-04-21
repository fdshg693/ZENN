#!/usr/bin/env node
import { readFileSync } from 'fs';

const input = JSON.parse(readFileSync(0, 'utf-8'));
const filePath = input.tool_input?.file_path ?? '';
const isClaudeDir = filePath.replace(/\\/g, '/').includes('/.claude/');

if (isClaudeDir) {
  console.log(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PermissionRequest',
      decision: { behavior: 'allow' }
    }
  }));
}
process.exit(0);
