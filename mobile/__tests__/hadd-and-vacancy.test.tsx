import { screen } from '@testing-library/react-native';
import { readdirSync, readFileSync } from 'fs';
import { join } from 'path';

import { Hadd, Vacancy } from '@/components';
import { toNumber } from '@/utils/present';
import { renderWithHarness } from './helpers';

/**
 * «الحدّ» و«الفراغ المشروح» — العنصران اللذان تراهما المالكة أكثر من غيرهما.
 *
 * في الأسابيع الأولى: لا صفقات، ولا مركز، ولا عيّنة، ولا تعارضات. فأكثر ما
 * سيُعرض عليها هو **الصفر والفراغ**. وهذه الاختبارات تحرس أن كليهما يُقرأ
 * معلومةً لا عطلاً.
 */

// ---------------------------------------------------------------------------
// toNumber — الحارس الذي يمنع رقماً مُختلَقاً من الوصول إلى مقياس
// ---------------------------------------------------------------------------
describe('toNumber', () => {
  it('يعيد null لا صفراً على نصّ فارغ', () => {
    /**
     * **هذا هو سبب وجود الدالة.** `Number('')` يعطي **صفراً**، وصفرٌ
     * مُختلَق يُرسم على «الحدّ» فيبدو قياساً حقيقياً: علامة عند الطرف
     * تقول «لم يُستهلك شيء» بينما الحقيقة «لا أعرف».
     */
    expect(toNumber('')).toBeNull();
    expect(toNumber('   ')).toBeNull();
    expect(toNumber(null)).toBeNull();
    expect(toNumber(undefined)).toBeNull();
  });

  it('يقرأ فاصل الآلاف وعلامة الموجب الصريحة', () => {
    expect(toNumber('1,234.50')).toBe(1234.5);
    expect(toNumber('+0.75')).toBe(0.75);
  });

  it('يقرأ السالب اليونيكودي لا ناقص ASCII وحده', () => {
    // الخادم ينسّق السوالب بـ U+2212، و`Number('−1')` يعطي NaN.
    expect(toNumber('−1.25')).toBe(-1.25);
    expect(toNumber('-1.25')).toBe(-1.25);
  });

  it('يقرأ الأرقام العربية-الهندية وفاصلتها العشرية', () => {
    expect(toNumber('١٢٣')).toBe(123);
    expect(toNumber('١٫٥')).toBe(1.5);
  });

  it('يرفض ما ليس رقماً بدل أن يخمّنه', () => {
    expect(toNumber('غير متاح')).toBeNull();
    expect(toNumber('—')).toBeNull();
    expect(toNumber('-')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// الحدّ
// ---------------------------------------------------------------------------
describe('Hadd', () => {
  it('علامة الموضع ظاهرة عند صفر بالمئة', () => {
    /**
     * القاعدة الأولى للعنصر. مؤشّرٌ يختفي عند الصفر يجعل الشاشة تبدو معطوبة
     * وهي سليمة — وهذه أكثر الحالات وقوعاً في الأسابيع الأولى.
     */
    renderWithHarness(<Hadd testID="h" value={0} max={1} />);
    expect(screen.getByTestId('h-tick')).toBeTruthy();
  });

  it('علامة الموضع ظاهرة عند الامتلاء أيضاً', () => {
    renderWithHarness(<Hadd testID="h" value={1} max={1} />);
    expect(screen.getByTestId('h-tick')).toBeTruthy();
  });

  it('لا ينهار على مدىً منعدم أو مقلوب', () => {
    // مدىً صفريّ يقع فعلاً: وقفٌ يساوي الهدف، أو حدٌّ لم يُحتسب بعد.
    expect(() =>
      renderWithHarness(<Hadd testID="a" value={5} min={3} max={3} />),
    ).not.toThrow();
    expect(() =>
      renderWithHarness(<Hadd testID="b" value={5} min={9} max={1} />),
    ).not.toThrow();
  });

  it('لا ينهار على قيمة غير محدودة', () => {
    expect(() =>
      renderWithHarness(<Hadd testID="c" value={Number.NaN} max={1} />),
    ).not.toThrow();
  });

  it('ينطق التسمية والقراءة معاً — لا رقماً بلا معناه', () => {
    renderWithHarness(
      <Hadd testID="h" value={0.4} max={1} label="المستهلَك" readout="0.20 من 0.50" />,
    );
    const bar = screen.getByRole('progressbar');
    expect(bar.props.accessibilityLabel).toContain('المستهلَك');
    expect(bar.props.accessibilityLabel).toContain('0.20 من 0.50');
  });

  it('يعلن المدى والقيمة للقارئ الصوتي', () => {
    renderWithHarness(<Hadd testID="h" value={3} min={1} max={7} />);
    expect(screen.getByRole('progressbar').props.accessibilityValue).toEqual({
      min: 1,
      max: 7,
      now: 3,
    });
  });
});

// ---------------------------------------------------------------------------
// الفراغ المشروح
// ---------------------------------------------------------------------------
describe('Vacancy', () => {
  it('يعرض الحقول الثلاثة', () => {
    renderWithHarness(
      <Vacancy what="لا مركز مفتوح." why="لا أدخل ببيانات ناقصة." next="عند فتح السوق." />,
    );
    expect(screen.getByText('لا مركز مفتوح.')).toBeTruthy();
    expect(screen.getByText('لا أدخل ببيانات ناقصة.')).toBeTruthy();
    expect(screen.getByText('عند فتح السوق.')).toBeTruthy();
  });

  it('يُنطق كجملة واحدة لا كثلاث قصاصات', () => {
    renderWithHarness(<Vacancy testID="v" what="لا صفقات." why="لم يُرسَل أمر." />);
    expect(screen.getByTestId('v').props.accessibilityLabel).toBe('لا صفقات.، لم يُرسَل أمر.');
  });

  it('يُسقط «ما التالي» حين لا يكون معروفاً ولا يخترع له نصّاً', () => {
    /**
     * الحقل الثالث هو ما يحوّل الفراغ من قلق إلى معلومة — ولذلك بالذات
     * لا يجوز ملؤه بعبارة مطمئنة غير مسنودة.
     */
    renderWithHarness(<Vacancy testID="v" what="لا قيود." />);
    expect(screen.getByTestId('v').props.accessibilityLabel).toBe('لا قيود.');
  });
});

// ---------------------------------------------------------------------------
// حارس ساكن — لئلّا يعود الفراغ الصامت
// ---------------------------------------------------------------------------
describe('لا شاشة تعرض فراغاً بلا تفسير', () => {
  const SCREENS = join(__dirname, '..', 'app', '(app)');

  it('لا شاشة تستعمل EmptyState بعد اليوم', () => {
    /**
     * `EmptyState` يعرض **رسالةً واحدة**. وثلاث عشرة شاشة كانت تقول «لا
     * صفقات مسجّلة بعد.» ثم تصمت — فتُقرأ «معطوب» بينما النظام سليم يعمل.
     *
     * وهذا فحصٌ ساكن لأن الانحدار هنا صامت: شاشةٌ جديدة تنسخ نمط شاشة قديمة،
     * فتمرّ كل اختبارات التصيير وهي تعرض فراغاً بلا سبب ولا «ما التالي».
     * المكوّن نفسه يبقى في `States.tsx` لمواضع أخرى — الممنوع استعماله شاشةً.
     */
    const offenders = readdirSync(SCREENS)
      .filter((f) => f.endsWith('.tsx'))
      .filter((f) => /\bEmptyState\b/.test(readFileSync(join(SCREENS, f), 'utf8')));

    expect(offenders).toEqual([]);
  });

  it('كل نصّ فراغ مصدره ar.ts لا الشاشة', () => {
    /**
     * قاعدة `ar.ts` مكتوبة في رأسه ومخروقة من قبل — فصارت ستّ صيغ لمعنى
     * واحد. فيُفحص هنا أن حقول `Vacancy` تأتي مراجعَ لا نصوصاً مثبَّتة.
     */
    const literals: string[] = [];
    for (const file of readdirSync(SCREENS).filter((f) => f.endsWith('.tsx'))) {
      const source = readFileSync(join(SCREENS, file), 'utf8');
      for (const match of source.matchAll(/\s(what|why|next)="([^"]*)"/g)) {
        literals.push(`${file}: ${match[1]}="${match[2]}"`);
      }
    }
    expect(literals).toEqual([]);
  });
});
