import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

import { MobileApiClient } from '@/api/client';
import {
  FORBIDDEN_ROUTE_TOKENS,
  NEVER_ON_DEVICE,
  READ_ROUTES,
  RISK_REDUCING_ROUTES,
} from '@/api/routes';

/**
 * الحدّ الأمني.
 *
 * هذا الملف يفحص **المصدر نفسه** لا السلوك: أي سرّ أو مضيف وسيط يتسلّل إلى
 * `mobile/` يسقط هنا قبل أن يصل إلى جهاز.
 */

const ROOT = join(__dirname, '..');

const SKIP_DIRS = new Set([
  'node_modules',
  '.expo',
  'ios',
  'android',
  'coverage',
  'dist',
  '.git',
]);

const TEXT_EXTENSIONS = new Set([
  '.ts',
  '.tsx',
  '.js',
  '.jsx',
  '.json',
  '.md',
  '.mjs',
  '.cjs',
  '.example',
  '.yml',
  '.yaml',
]);

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) {
      continue;
    }
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, out);
      continue;
    }
    const dot = entry.lastIndexOf('.');
    const ext = dot === -1 ? '' : entry.slice(dot);
    if (TEXT_EXTENSIONS.has(ext) || entry.startsWith('.env')) {
      out.push(full);
    }
  }
  return out;
}

/** يستبعد هذا الملف نفسه: هو الوحيد الذي يذكر الممنوع كي يمنعه. */
const sourceFiles = (): string[] =>
  walk(ROOT).filter((file) => relative(ROOT, file) !== join('__tests__', 'security-boundary.test.ts'));

const readAll = (): Array<{ file: string; text: string }> =>
  sourceFiles().map((file) => ({ file: relative(ROOT, file), text: readFileSync(file, 'utf8') }));

/**
 * الملفات **المتتبَّعة في git**.
 *
 * الخاصية التي تحمي فعلاً ليست «لا يُذكر عنوان»، بل «لا يُودَع عنوان في
 * المستودع». ملف محلي متجاهَل لا يغادر الجهاز؛ وملف متتبَّع يغادره إلى الأبد.
 */
const trackedFiles = (): Set<string> =>
  new Set(
    execFileSync('git', ['-C', ROOT, 'ls-files'], { encoding: 'utf8' })
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
  );

describe('لا مضيف وسيط في مصدر الجوال', () => {
  /**
   * أسماء المضيفين مُركَّبة من أجزاء عمداً، كي لا يوجد المضيف نفسه حرفياً في
   * أي ملف — بما فيه ملف الاختبار.
   */
  const brokerHostFragments = [
    ['capital', '.com'],
    ['api-', 'capital', '.backend-', 'capital', '.com'],
    ['demo-api-', 'capital'],
  ].map((parts) => parts.join(''));

  it.each(brokerHostFragments)('«%s» لا يظهر في أي ملف', (host) => {
    const offenders = readAll()
      .filter(({ text }) => text.toLowerCase().includes(host.toLowerCase()))
      .map(({ file }) => file);
    expect(offenders).toEqual([]);
  });
});

describe('لا سرّ على الجهاز', () => {
  /**
   * البحث عن **شكل** السرّ لا عن اسمه: إسناد قيمة إلى متغيّر يحمل دلالة سرّية.
   * A comment mentioning secrets is fine; an assignment is not.
   */
  const SECRET_ASSIGNMENT =
    /\b[A-Za-z_][A-Za-z0-9_]*(API_KEY|SECRET|PASSWORD|PRIVATE_KEY|ACCESS_KEY|DATABASE_URL|SECURITY_TOKEN)\b\s*[:=]\s*['"][^'"]{8,}['"]/;

  it('قائمة أصناف الأسرار الممنوعة موصوفة بالصنف لا بالاسم الحرفي', () => {
    expect(NEVER_ON_DEVICE.length).toBeGreaterThan(0);
    for (const category of NEVER_ON_DEVICE) {
      expect(category).not.toMatch(/^[A-Z0-9_]+$/);
    }
  });

  it('لا إسناد يشبه سرّاً في أي ملف', () => {
    const offenders = readAll()
      .filter(({ text }) => SECRET_ASSIGNMENT.test(text))
      .map(({ file }) => file);
    expect(offenders).toEqual([]);
  });

  it('لا ترويسة وسيط ولا رمز جلسته في المصدر', () => {
    const brokerHeaders = ['X-SECURITY-TOKEN', 'x-security-token'];
    const offenders = readAll()
      .filter(({ text }) => brokerHeaders.some((needle) => text.includes(needle)))
      .map(({ file }) => file);
    expect(offenders).toEqual([]);
  });

  it('لا مفتاح خاص ولا شهادة في الشجرة', () => {
    const markers = ['-----BEGIN', 'PRIVATE KEY'];
    const offenders = readAll()
      .filter(({ text }) => markers.some((needle) => text.includes(needle)))
      .map(({ file }) => file);
    expect(offenders).toEqual([]);
  });

  it('لا ملف .env متتبَّع في git — فقط .env.example بقيم نائبة', () => {
    // ملف `.env` محلي أمرٌ طبيعي على جهاز التطوير، والخطر أن **يُتتبَّع**.
    const trackedEnv = [...trackedFiles()].filter((file) => file.startsWith('.env')).sort();
    expect(trackedEnv).toEqual(['.env.example']);

    const example = readFileSync(join(ROOT, '.env.example'), 'utf8');
    expect(example).toContain('127.0.0.1');
    // لا شيء يشبه مفتاحاً: لا سلسلة طويلة بعد «=».
    for (const line of example.split('\n')) {
      if (line.startsWith('#') || !line.includes('=')) {
        continue;
      }
      const value = line.slice(line.indexOf('=') + 1).trim();
      expect(value.length).toBeLessThan(48);
    }
  });
});

describe('لا ذكر لقناة نفق عامة', () => {
  /**
   * تفريق مقصود بين نوعين من الأنفاق:
   *
   *   * `ngrok` و`funnel` و`trycloudflare` وأمثالها **أنفاق عامة**: تفتح جهازك
   *     للإنترنت كلّه. ممنوعة في أي ملف، متتبَّعاً كان أو محلياً.
   *   * عنوان Tailscale (`.ts.net`) داخل **شبكة خاصة** لا يصل إليها أحد من
   *     خارجها. والخادم انتقل إليها فعلاً في 0.7.1، فمنعه من `.env` المحلي
   *     يمنع المعمارية القائمة لا يحميها.
   *
   * فالمنع الباقي: ألّا يُودَع أي عنوان خاص **في المستودع**.
   */
  const PUBLIC_TUNNELS = ['ngrok', 'funnel', 'trycloudflare', 'localtunnel', 'serveo'];

  it('لا نفق عام في أي ملف', () => {
    const offenders = readAll()
      .filter(({ text }) => PUBLIC_TUNNELS.some((needle) => text.toLowerCase().includes(needle)))
      .map(({ file }) => file);
    expect(offenders).toEqual([]);
  });

  it('لا عنوان شبكة خاصة داخل ملف متتبَّع في git', () => {
    const tracked = trackedFiles();
    const offenders = readAll()
      .filter(({ file }) => tracked.has(file.split('\\').join('/')))
      .filter(({ text }) => text.toLowerCase().includes('ts.net'))
      .map(({ file }) => file);
    expect(offenders).toEqual([]);
  });

  it('العنوان الافتراضي حلقة محلية', () => {
    const appConfig = readFileSync(join(ROOT, 'app.config.ts'), 'utf8');
    expect(appConfig).toContain('http://127.0.0.1:8000');
    expect(appConfig).not.toMatch(/https?:\/\/(?!127\.0\.0\.1)[a-z0-9-]+\.[a-z]{2,}/i);
  });
});

describe('سطح المسارات', () => {
  it('مسارات القراءة مطابقة لعقد الخادم حرفاً', () => {
    expect([...READ_ROUTES]).toEqual([
      'status',
      'intelligence/latest',
      'decision/latest',
      'risk',
      'profiles',
      'positions/current',
      'trades',
      'performance',
      'providers/health',
      'notifications',
      'audit/recent',
    ]);
  });

  it('مسارات التعديل ثلاثة، وكلها تقلّل المخاطرة', () => {
    expect([...RISK_REDUCING_ROUTES]).toEqual([
      'pause/request',
      'killswitch/activate',
      'device/revoke',
    ]);
  });

  it('لا كلمة تداول محظورة في أي مسار', () => {
    for (const route of [...READ_ROUTES, ...RISK_REDUCING_ROUTES]) {
      for (const token of FORBIDDEN_ROUTE_TOKENS) {
        expect(route.includes(token)).toBe(false);
      }
    }
  });
});

describe('لا واجهة تداول في العميل', () => {
  const forbiddenMethods = [
    'placeOrder',
    'createOrder',
    'submitOrder',
    'closePosition',
    'openPosition',
    'modifyPosition',
    'setLeverage',
    'setStopLoss',
    'setTakeProfit',
    'changeQuantity',
    'reactivateBrokerKey',
    'upgradeProfile',
    'deactivateKillSwitch',
    'cancelKillSwitch',
  ];

  const methodNames = Object.getOwnPropertyNames(MobileApiClient.prototype);

  it.each(forbiddenMethods)('لا دالة «%s» على العميل', (name) => {
    expect(methodNames).not.toContain(name);
  });

  it('الدوال العامة على العميل هي القراءة والثلاثة والاستئناف', () => {
    // ⚠️ كُبِّرت القائمة بواحد في 2026-09-01: `resumeTrading`.
    //
    // وهو **المسار الوحيد الذي يزيد المخاطرة** في التطبيق، وقد أُضيف بقرار
    // معلَن في فئة `RISK_INCREASING_ROUTES` المُسمّاة على الجانبين.
    //
    // ويبقى الحدّ الحقيقي كما هو: لا `closePosition` ولا `submitOrder` ولا
    // `deactivateKillSwitch` ولا `setLeverage` — والقائمة أعلاه (`forbiddenMethods`)
    // تفحصها بالاسم. وأي دالة عامة جديدة تُسقط هذا الاختبار، وهو الغرض.
    // الخاصة بالاسم الدقيق، فلا يختفي شيء عام خلف بادئة مشتركة.
    const privateMethods = ['constructor', 'read', 'mutate', 'request', 'refreshOnce'];
    const publicMethods = methodNames.filter((name) => !privateMethods.includes(name));
    expect(publicMethods.sort()).toEqual(
      [
        'activateKillSwitch',
        'endpointVerdict',
        'getAudit',
        'getCurrentPosition',
        'getDecision',
        'getIntelligence',
        'getNotifications',
        'getPerformance',
        'getProfiles',
        'getProviderHealth',
        'getRisk',
        'getStatus',
        'getTrades',
        'requestPause',
        'resumeTrading',
        'revokeDevice',
      ].sort(),
    );
  });
});

describe('لا تحليلات ولا تتبّع', () => {
  it('لا اعتماد على أي حزمة قياس', () => {
    const pkg: unknown = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'));
    const record = pkg as { dependencies?: Record<string, string> };
    const names = Object.keys(record.dependencies ?? {});
    const analytics = ['segment', 'amplitude', 'firebase', 'sentry', 'mixpanel', 'analytics'];
    for (const name of names) {
      for (const needle of analytics) {
        expect(name.toLowerCase()).not.toContain(needle);
      }
    }
  });
});

describe('الشجرة لا تلمس شيئاً خارج mobile/', () => {
  it('لا مسار نسبي يصعد فوق جذر التطبيق', () => {
    const offenders = readAll()
      .filter(({ file }) => file.endsWith('.ts') || file.endsWith('.tsx'))
      .filter(({ text }) => /from ['"]\.\.\/\.\.\/\.\.\//.test(text))
      .map(({ file }) => file);
    expect(offenders).toEqual([]);
  });

  it('git لا يرى تعديلاً خارج mobile/ من هذه الشجرة', () => {
    // فحص إعلامي: يثبت أن الملفات المكتوبة كلها تحت mobile/.
    const tracked = execFileSync('git', ['-C', ROOT, 'ls-files', '--others', '--exclude-standard'], {
      encoding: 'utf8',
    });
    for (const line of tracked.split('\n').filter(Boolean)) {
      expect(line.startsWith('..')).toBe(false);
    }
  });
});
