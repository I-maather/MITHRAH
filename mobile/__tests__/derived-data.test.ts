/**
 * ذاكرةُ البناء لا تعود إلى القرص الداخلي — ولا صامتةً.
 *
 * ## ما وُجد يوم ٥ سبتمبر ٢٠٢٦
 *
 * القرصُ الداخلي 99% ممتلئ، `3.2GB` متاحة، وذاكرةُ بناء Xcode وحدها `3.4GB`.
 * فنُقلت إلى الوعاء الخارجي. والخطرُ الذي يلي النقلَ ليس الفشل — الفشلُ
 * يُرى — بل **النجاحُ الكاذب**: مسارٌ غائبٌ يُنشئه Xcode على الداخلي بلا
 * سؤال، فيمتلئ القرصُ من جديد ونحن نظنّه على الخارجي.
 *
 * فهذه الحراسة تمنع عودةَ البديل الصامت إلى السكربتات.
 */
import { readFileSync } from 'fs';
import { join } from 'path';

const root = join(__dirname, '..');
const read = (p: string): string => readFileSync(join(root, p), 'utf8');

const guard = read('scripts/derived_data_guard.sh');
const buildEnv = read('scripts/build_env.sh');

describe('حارسُ ذاكرة البناء', () => {
  it('يتحقّق من البصمة لا من الاسم', () => {
    // اسمُ «MATHRAH» يمكن أن يحمله أيُّ وعاءٍ يُنشأ بالخطأ. البصمة لا تُقلَّد.
    expect(guard).toContain('1BC3335A-DE1C-4E3B-9F53-3F98B4355EF0');
    expect(guard).toMatch(/Volume UUID/);
    expect(guard).toMatch(/uuid" *!= *"\$MATHRAH_VOLUME_UUID/);
  });

  it('يتحقّق أن الوعاء قابلٌ للفصل — أي ليس القرصَ الداخلي', () => {
    expect(guard).toMatch(/Removable Media/);
  });

  it('يتحقّق أن المسار على الوعاء بجهازه لا بنصّه', () => {
    // وصلةٌ رمزية تجعل المسار يبدو خارجياً وهو داخليّ.
    expect(guard).toMatch(/dev_target/);
    expect(guard).toMatch(/df /);
  });

  it('يفشل بوضوح ولا يخترع بديلاً', () => {
    expect(guard).toMatch(/⛔/);
    expect(guard).toMatch(/ولا بديلَ على القرص الداخلي/);
  });
});

describe('لا بديلَ على القرص الداخلي', () => {
  const scripts = [
    ['scripts/derived_data_guard.sh', guard],
    ['scripts/build_env.sh', buildEnv],
  ] as const;

  it.each(scripts)('%s لا يذكر مسار DerivedData الداخلي', (_name, body) => {
    // `~/Library/Developer/Xcode/DerivedData` هو الموضع الذي هربنا منه.
    // ذكرُه في سكربتِ بناءٍ يعني — غالباً — بديلاً عند الفشل.
    expect(body).not.toMatch(/Library\/Developer\/Xcode\/DerivedData/);
  });

  it.each(scripts)('%s لا يحتوي بديلاً بعد `||` لمسار داخلي', (_name, body) => {
    expect(body).not.toMatch(/\|\|\s*(export\s+)?MATHRAH_DERIVED_DATA=/);
  });
});

describe('غلافُ البناء يستدعي الحارس', () => {
  it('يُحمّل الحارس ويوقف البناء عند فشله', () => {
    expect(buildEnv).toMatch(/source .*derived_data_guard\.sh/);
    expect(buildEnv).toMatch(/require_external_derived_data \|\| exit 1/);
  });

  it('يستدعي الحارس قبل تسليم التنفيذ', () => {
    // `exec "$@"` يستبدل العملية: ما بعده لا يُنفَّذ أبداً.
    const callIndex = buildEnv.indexOf('require_external_derived_data');
    const execIndex = buildEnv.indexOf('exec "$@"');
    expect(callIndex).toBeGreaterThan(-1);
    expect(execIndex).toBeGreaterThan(-1);
    expect(callIndex).toBeLessThan(execIndex);
  });

  it('ما زال يثبّت الكوميت — الحارسُ أُضيف ولم يُزِح', () => {
    expect(buildEnv).toMatch(/EXPO_PUBLIC_BUILD_COMMIT/);
    expect(buildEnv).toMatch(/EXPO_PUBLIC_BUILD_TIME/);
  });
});
