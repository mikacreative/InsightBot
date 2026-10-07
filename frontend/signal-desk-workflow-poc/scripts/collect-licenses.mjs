import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const visited = new Set();
const notices = [];

function add(name) {
  if (visited.has(name)) return;
  visited.add(name);
  const directory = join(root, 'node_modules', name);
  if (!existsSync(directory)) return;
  const metadata = JSON.parse(readFileSync(join(directory, 'package.json'), 'utf8'));
  const files = readdirSync(directory).filter(file => /^(license|licence|copying)(\..*)?$/i.test(file));
  if (!files.length) throw new Error(`Missing license text for ${name}; check the installed package.`);
  notices.push([`${metadata.name} ${metadata.version} — ${metadata.license || 'see license text'}`,
    ...files.map(file => readFileSync(join(directory, file), 'utf8'))].join('\n\n'));
  for (const dependency of Object.keys(metadata.dependencies || {})) add(dependency);
  for (const dependency of Object.keys(metadata.optionalDependencies || {})) add(dependency);
}

const metadata = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
for (const name of Object.keys(metadata.dependencies)) add(name);
mkdirSync(join(root, 'public'), { recursive: true });
writeFileSync(join(root, 'public', 'third-party-licenses.txt'),
  `Signal Desk workflow prototype — third-party notices\n\n${notices.sort().join('\n\n' + '-'.repeat(78) + '\n\n')}`.trimEnd() + '\n');
console.log(`Collected license texts for ${notices.length} production dependency packages.`);
