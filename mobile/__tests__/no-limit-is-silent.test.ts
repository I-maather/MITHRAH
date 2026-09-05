import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';

/**
 * حدٌّ يحمله العقد ولا يُعرض حدٌّ صامت.
 *
 * `RiskData` كان يحمل سقفَ المراكز وسقفَ أوامر الدخول اليومية والخسائر
 * المتتالية وحدَّي التراجع — **ولا واحدٌ منها معروضاً**. والعيب `C2` —
 * أربعةُ مراكز مقابل سقفٍ ثلاثة، ومركزان على GBPUSD — كان سيُرى على
 * الشاشة في اليوم نفسه لو عُرض حقلان موجودان في العقد أصلاً.
 *
 * فالمقياس هنا ليس «هل الشاشة جميلة» بل: **أيّ حقلٍ في العقد لا موضع له
 * على الشاشة، ولماذا**. والاستثناء يُكتَب هنا بسببه، لا يُترك صامتاً.
 */

const MOBILE = join(__dirname, '..');
const TYPES = join(MOBILE, 'src', 'api', 'types.ts');
const SCREENS = join(MOBILE, 'app', '(app)');

/** حقولٌ لا تُعرض، ولكلٍّ سببٌ مكتوب. */
const EXEMPT: Record<string, string> = {
  editable_from_device: 'علمٌ للعميل لا معلومةٌ للمستخدمة — الحدود لا تُعدَّل من الجهاز.',
  currency: 'يظهر داخل القيم نفسها لا حقلاً مستقلاً.',
  profile: 'المعرّف الآلي؛ المعروض هو `profile_name_ar`.',
  diverged: 'علمٌ يُشغّل عرض `note_ar` — والملاحظة هي المعروضة.',
};

function riskDataKeys(): string[] {
  const source = readFileSync(TYPES, 'utf8');
  const start = source.indexOf('export interface RiskData {');
  expect(start).toBeGreaterThan(-1);
  let depth = 0;
  let end = start;
  for (let i = source.indexOf('{', start); i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  const body = source.slice(start, end);
  const keys = new Set<string>();
  for (const match of body.matchAll(/^\s{2,}([a-z_][a-z0-9_]*)\??:/gim)) {
    const key = match[1];
    if (key !== undefined) {
      keys.add(key);
    }
  }
  return [...keys];
}

function screenSources(): string {
  return readdirSync(SCREENS)
    .filter((name) => name.endsWith('.tsx'))
    .map((name) => readFileSync(join(SCREENS, name), 'utf8'))
    .join('\n');
}

describe('لا حقلَ حدٍّ صامت', () => {
  it('العقد يُقرأ فعلاً — وإلا فالاختبار يقيس لا شيء', () => {
    const keys = riskDataKeys();
    expect(keys).toContain('max_open_positions');
    expect(keys).toContain('absolute_loss_boundary');
    expect(keys.length).toBeGreaterThan(15);
  });

  it('**كل حقل معروضٌ أو مُستثنى بسببٍ مكتوب**', () => {
    const screens = screenSources();
    const silent = riskDataKeys().filter(
      (key) => !(key in EXEMPT) && !screens.includes(key),
    );
    expect(silent).toEqual([]);
  });

  it('لا استثناءَ ميّت — كل مُستثنى ما زال في العقد', () => {
    const keys = new Set(riskDataKeys());
    const stale = Object.keys(EXEMPT).filter((key) => !keys.has(key));
    expect(stale).toEqual([]);
  });

  it('لكل استثناءٍ سببٌ لا كلمة', () => {
    for (const [key, reason] of Object.entries(EXEMPT)) {
      expect(reason.length).toBeGreaterThan(20);
      expect(key).not.toEqual('');
    }
  });
});
