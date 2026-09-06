import { screen } from '@testing-library/react-native';

import HomeScreen from '../app/(app)/home';
import { Field } from '@/components';
import { fixtures, isPreviewMode } from '@/fixtures';
import { t } from '@/i18n';
import { renderWithHarness } from './helpers';

/**
 * **وضعُ المعاينة يُطلَب هنا صراحةً.**
 *
 * كان `PREVIEW_DATA_ENABLED` يصير `true` تلقائياً حين `__DEV__` — وهي صحيحة
 * داخل Jest. فكانت هذه الشاشات تُختبَر على بيانات المعاينة بلا أن يُعلن ذلك،
 * وكان وضعُ المعاينة يمنع طلب الشبكة، فبقي مسار الخادم بلا اختبارٍ هنا
 * (يغطّيه `sparse-data.test.tsx` صراحةً).
 *
 * صار الافتراضُ إطفاءً، فيُعلَن الاعتماد بدل أن يُورَث.
 */
jest.mock('@/api/config', () => ({
  ...jest.requireActual('@/api/config'),
  PREVIEW_DATA_ENABLED: true,
}));


/**
 * اللوحة الرئيسية تعرض ما اتُّفق عليه، كاملاً.
 */

/**
 * **ما بقي في «اليوم» بعد النقل.**
 *
 * النموذج المعتمد ينهي هذه الشاشة عند المراكز. وكان بعدها عشرُ بطاقات —
 * وهو العيبُ المكتوب في رأس `home.tsx` بيدنا: «تسع بطاقات متساوية الوزن،
 * والشاشة التي كل شيء فيها مهمّ لا شيء فيها مهمّ». عولج أعلى الشاشة يومها
 * ولم يُعالج أسفلها.
 */
const REQUIRED_CARDS = [
  'allocated-card', // الرقم الرئيسي: الحصّة المخصَّصة، ومعها مخاطرةُ اليوم
  'agent-card', // ما يفكر فيه الوكيل — الفراغ الذي لا يملؤه أحد
  'home-chart-card', // على أيّ سعرٍ كان هذا الحكم
];

/**
 * **وما انتقل لا يعود.**
 *
 * هذه ليست قائمةَ نظافة: عودةُ أيٍّ منها إلى «اليوم» تُعيد الذيلَ الذي
 * أُزيل، ولا يُلحَظ ذلك بالعين إلا بعد أن يطول من جديد.
 */
const MOVED_AWAY = [
  'portfolio-card', // رصيدُ الوسيط ← النظام
  'system-card', // حالة التشغيل ← النظام
  'risk-week-card', // الأسبوع ← المحفظة
  'limits-card', // الحدود ← المحفظة
  'profile-card', // الملف ← النظام
  'decision-card', // القرار ← صفُّ انتقالٍ وحده
  'strategy-card', // الاستراتيجية ← النظام
  'event-card', // الحدث ← النظام
  'position-card', // المركز ← المحفظة
];

describe('محتوى اللوحة', () => {
  beforeEach(() => {
    renderWithHarness(<HomeScreen />, { status: 'UNLOCKED' });
  });

  it.each(REQUIRED_CARDS)('البطاقة «%s» موجودة', (testID) => {
    expect(screen.getByTestId(testID)).toBeTruthy();
  });

  it.each(MOVED_AWAY)('البطاقة «%s» لم تعد في «اليوم»', (testID) => {
    expect(screen.queryByTestId(testID)).toBeNull();
  });

  it('**الرقم الرئيسي رقمٌ واحد** — لا رقمان متساويا الوزن', () => {
    /*
      كانت الشاشة تعرض رصيدَ الوسيط والمرجعيَّ متجاورين متساويي الوزن،
      فلا تقول أيُّهما الجواب — وقرارُك أنّ المخصَّص هو المقياس.
    */
    expect(screen.getByTestId('allocated-equity')).toBeTruthy();
    expect(screen.getByTestId('allocated-baseline')).toBeTruthy();
    expect(screen.queryByTestId('portfolio-broker')).toBeNull();
  });

  it('مخاطرةُ اليوم في البطاقة نفسها — سؤالٌ واحد لا بطاقتان', () => {
    expect(screen.getByTestId('risk-meter-daily')).toBeTruthy();
    expect(screen.getByTestId('risk-hadd')).toBeTruthy();
  });

  it('مسار اليوم يصل إلى الشاشة', () => {
    expect(fixtures.participation.steps.length).toBeGreaterThan(0);
    expect(screen.getByTestId('day-path')).toBeTruthy();
  });

  it('**سببُ الامتناع يُعرض مرّةً واحدة لا ثلاثاً**', () => {
    /*
      رُئي على الجهاز يوم ٦ سبتمبر: «فتحُ المراكز موقوفٌ بقرارك…» ثلاثَ
      مرّات في شاشةٍ واحدة — سطراً تحت الحكم، ثم متناً في بطاقة الوكيل،
      والحكمُ نفسه مرّتين. وتكرارُ الجملة لا يؤكّدها: يجعل الشاشة تبدو
      معطوبة، وهو أوّلُ ما يُفقد الثقة في واجهةٍ يُفترض أن تكون هادئة.
    */
    const reason = fixtures.status.no_trade_reason_ar!;
    expect(screen.queryAllByText(reason)).toHaveLength(1);
    expect(screen.getByTestId('agent-card')).toBeTruthy();
    expect(screen.queryByTestId('no-trade-reason')).toBeNull();
  });

  it('**والحكمُ يُقال مرّةً واحدة** — في التحية وحدها', () => {
    const verdictNodes = screen.queryAllByText(/مراكز مفتوحة|لا شيء يحتاجكِ|لم أتداول/);
    expect(verdictNodes.length).toBeLessThanOrEqual(1);
  });

  it('لا بطاقةَ داخل بطاقة — صفُّ القرار سطرٌ لا علبة', () => {
    expect(screen.queryByTestId('today-more-card')).toBeNull();
    expect(screen.getByTestId('nav-decision')).toBeTruthy();
  });

  it('**رسم الرئيسية على إطار القرار وحده** — لا منتقيات ولا إيحاء بغيره', () => {
    /**
     * الرئيسية ليست شاشة تصفّح: منتقي أربع أدواتٍ وخمسة أطرٍ فيها يجعلها
     * شاشة الشموع مكرّرة — ويوحي بأن النظام يقرّر على أيّها اختير.
     */
    expect(screen.getByTestId('home-chart')).toBeTruthy();
    expect(screen.getByTestId('home-chart-card')).toHaveTextContent(
      new RegExp(t.chart.frames[fixtures.candles.decision_resolution]!),
    );
    expect(screen.queryByTestId('chart-frame-HOUR_4')).toBeNull();
    expect(screen.queryByTestId('chart-pick-EURUSD')).toBeNull();
    // وصفٌّ إلى الشاشة الكاملة: التفصيل يُتاح ولا يُحشَر.
    expect(screen.getByTestId('nav-chart')).toBeTruthy();
  });

  it('**بلا مركز: لا خطوط على الرسم، ويُقال ذلك** — لا خطٌّ عند الصفر', () => {
    expect(fixtures.candles.levels.symbol).toBeNull();
    expect(screen.queryByTestId('chart-level-stop')).toBeNull();
    expect(screen.getByTestId('home-chart-card')).toHaveTextContent(/لا مركز مفتوح/);
  });

  it('محور الوقت في الرئيسية يوافق إطار القرار', () => {
    // اليومي يُوسَم بالتاريخ لا بالساعة.
    expect(screen.getByTestId('chart-time-axis')).toHaveTextContent(/\d{2}\/\d{2}/);
  });

  it('**تقول أيّ الحدّين يعمل** — لا تَعِد بحدٍّ أشدّ من العامل', () => {
    /**
     * كانت البطاقة تعرض حدود الملف والمحرّك ينفّذ حدود الدستور. والنصّ
     * يأتي من الخادم كاملاً: العميل لا يفسّر أيّهما أشدّ.
     */
    expect(screen.getByTestId('risk-binding')).toHaveTextContent(
      new RegExp(fixtures.risk.profile_binding_ar.slice(0, 24)),
    );
  });

  it('تقول صراحةً إنها لا تأذن بتنفيذ', () => {
    expect(screen.getByTestId('home-no-execution')).toHaveTextContent(t.common.noExecution);
  });

  it('**حالةُ المراكز تُقال دائماً** — إمّا ما يحتاج انتباهك، وإمّا فراغٌ مُعلَن', () => {
    /*
      واحدةٌ منهما لا كلتاهما ولا لا شيء: الصمتُ عن المراكز يُقرأ
      «لا مركز»، وهي دعوى معرفةٍ لا تُقال بالسكوت.
    */
    const shown = [
      screen.queryByTestId('attention-card'),
      screen.queryByTestId('no-position-empty'),
    ].filter((node) => node !== null);
    expect(shown).toHaveLength(1);
  });
});

describe('لا بيانات مُختلَقة', () => {
  it('القيمة الغائبة تُعرض «غير متاح» لا صفراً', () => {
    renderWithHarness(<Field label="قيمة" value={null} testID="missing-field" />, {
      status: 'UNLOCKED',
    });
    const field = screen.getByTestId('missing-field');
    expect(String(field.props.accessibilityLabel)).toContain(t.common.unavailable);
    expect(String(field.props.accessibilityLabel)).not.toContain('0');
  });

  it('القيمة الفارغة تُعامَل معاملة الغائبة', () => {
    renderWithHarness(<Field label="قيمة" value="" testID="empty-field" />, {
      status: 'UNLOCKED',
    });
    expect(String(screen.getByTestId('empty-field').props.accessibilityLabel)).toContain(
      t.common.unavailable,
    );
  });
});

describe('وسم بيانات المعاينة', () => {
  it('حين تُطلَب المعاينة تحمل الشاشة وسم «معاينة / Preview»', () => {
    expect(isPreviewMode()).toBe(true);
    renderWithHarness(<HomeScreen />, { status: 'UNLOCKED' });
    const banner = screen.getByTestId('preview-banner');
    expect(String(banner.props.accessibilityLabel)).toContain('معاينة');
    expect(String(banner.props.accessibilityLabel)).toContain('Preview');
    expect(String(banner.props.accessibilityLabel)).toContain('ليست حالة النظام الحقيقية');
  });

  it('كل قيمة في بيانات المعاينة موسومة أو محايدة، ولا تدّعي الإذن بالتنفيذ', () => {
    expect(fixtures.decision.authorises_execution).toBe(false);
    expect(fixtures.status.system_state_ar).toContain('معاينة');
    expect(fixtures.risk.editable_from_device).toBe(false);
    expect(fixtures.profiles.upgrade_requires_server).toBe(true);
  });
});
