#!/usr/bin/env node
/**
 * حارس `overrides`: لا تتجاوز نطاقاً أعلنه مستهلك.
 *
 * ## العطب الذي أوجد هذا الحارس
 *
 * أُضيفت سبعة `overrides` لخفض عدد تنبيهات `npm audit`. سبعتها — بلا
 * استثناء — رفعت الحزمة **خارج النطاق الذي يعلنه مستهلكها**. وواحدة منها
 * كسرت البناء كسراً كاملاً:
 *
 *     @expo/cli يعلن  tar: ^6.0.5
 *     الـoverride فرض tar: 7.5.22
 *
 * وtar 6 وحدةُ CommonJS، فـ`_interopRequireDefault` يعطي `.default`. أما
 * tar 7 فيضع `__esModule: true` بلا تصدير `default` — فصار
 * `_tar().default.extract` قراءةً لخاصية من `undefined`، وسقط
 * `expo prebuild` برسالة لا تدلّ على السبب:
 *
 *     Cannot read properties of undefined (reading 'extract')
 *
 * ## القاعدة
 *
 *     كل `override` يجب أن يُرضي **كل** نطاق يعلنه مستهلك في الشجرة.
 *
 * وإن لم توجد نسخة مُصلَّحة داخل النطاق المُعلَن، فالجواب ليس كسر النطاق:
 * الجواب توثيق الثغرة وإثبات عدم وصولها — وهو ما تفعله
 * `docs/MOBILE_DEPENDENCY_AUDIT.md`. لأن الحزم المعنية كلها **أدوات بناء
 * لا تُشحَن**، فرفعها قسراً لا يحمي التطبيق من شيء، ويخاطر بالبناء كله.
 *
 *     node scripts/check-overrides.mjs
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(import.meta.url);

/** @returns {any|null} */
function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return null;
  }
}

const pkg = readJson(join(ROOT, 'package.json'));
const overrides = pkg?.overrides ?? {};
const names = Object.keys(overrides);

if (names.length === 0) {
  console.log('   (لا overrides — لا شيء يُفحَص)');
  process.exit(0);
}

let semver;
try {
  semver = require('semver');
} catch {
  console.error('⛔ حزمة semver غير متاحة — لا يمكن التحقق. لا يُتخطّى الفحص بصمت.');
  process.exit(1);
}

/**
 * يمشي الشجرة ويجمع كل مستهلك لكل حزمة معنية، **مع مجلّده** — فالمجلّد هو
 * ما يسمح بحلّ النسخة التي يراها هو فعلاً، لا نسخة الجذر افتراضاً. الحزمة
 * المُتجاوَزة نادراً ما تكون في جذر `node_modules`؛ إنما تحت مستهلكها.
 */
function collectConsumers(wanted) {
  const found = new Map(wanted.map((n) => [n, []]));
  const walk = (dir, depth) => {
    if (depth > 8) return;
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;
      const full = join(dir, entry.name);
      if (entry.name.startsWith('@')) {
        walk(full, depth);
        continue;
      }
      const manifest = readJson(join(full, 'package.json'));
      if (manifest?.name) {
        for (const field of ['dependencies', 'peerDependencies']) {
          for (const [dep, range] of Object.entries(manifest[field] ?? {})) {
            if (found.has(dep)) {
              found.get(dep).push({ consumer: manifest.name, dir: full, field, range });
            }
          }
        }
      }
      const nested = join(full, 'node_modules');
      try {
        if (statSync(nested).isDirectory()) walk(nested, depth + 1);
      } catch {
        /* لا شجرة متداخلة */
      }
    }
  };
  walk(join(ROOT, 'node_modules'), 0);
  return found;
}

/**
 * حلّ node الحقيقي: يصعد من مجلّد المستهلك بحثاً عن `node_modules/<اسم>`.
 * هذا ما يراه `require` فعلاً — لا نسخة الجذر بالضرورة.
 */
function resolveVersionFrom(consumerDir, name) {
  let dir = consumerDir;
  for (let i = 0; i < 12; i += 1) {
    const candidate = readJson(join(dir, 'node_modules', name, 'package.json'));
    if (candidate?.version) return candidate.version;
    const parent = dirname(dir);
    if (parent === dir || dir === ROOT) break;
    dir = parent;
  }
  return readJson(join(ROOT, 'node_modules', name, 'package.json'))?.version ?? null;
}

const consumers = collectConsumers(names);
const violations = [];

for (const name of names) {
  const broken = [];
  for (const { consumer, dir, range } of consumers.get(name) ?? []) {
    const resolved = resolveVersionFrom(dir, name);
    if (!resolved) {
      broken.push(`${consumer} يعلن ${range} — ولا نسخة مثبَّتة يراها`);
    } else if (!semver.satisfies(resolved, range, { includePrerelease: true })) {
      broken.push(`${consumer} يعلن ${range} — والمحلولة ${resolved}`);
    }
  }
  if (broken.length > 0) violations.push({ name, broken });
}

if (violations.length > 0) {
  console.error('⛔ overrides تكسر نطاقات مُعلَنة:\n');
  for (const { name, broken } of violations) {
    console.error(`   ${name}`);
    for (const line of [...new Set(broken)]) console.error(`      ✗ ${line}`);
  }
  console.error(
    '\n   لا يُرفَع override خارج نطاق مستهلكه. إن لم توجد نسخة مُصلَّحة داخل\n' +
      '   النطاق، وثّقي الثغرة وأثبتي عدم وصولها في\n' +
      '   docs/MOBILE_DEPENDENCY_AUDIT.md بدل كسر البناء.',
  );
  process.exit(1);
}

console.log(`   (${names.length} override، كلها داخل النطاقات المُعلَنة)`);
