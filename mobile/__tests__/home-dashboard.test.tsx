import { screen } from '@testing-library/react-native';

import HomeScreen from '../app/(app)/home';
import { Field } from '@/components';
import { fixtures, isPreviewMode } from '@/fixtures';
import { t } from '@/i18n';
import { renderWithHarness } from './helpers';

/**
 * اللوحة الرئيسية تعرض ما اتُّفق عليه، كاملاً.
 */

const REQUIRED_CARDS = [
  // الشموع والمستويات صعدت إلى الرئيسية: الحكم يقول «لم أتداول»، والسؤال
  // الذي يليه فوراً «على أيّ سعرٍ حكمتَ؟» — وكان جوابُه شاشةً خلف لمستين.
  'home-chart-card',
  'system-card', // حالة النظام · اتصال الوسيط · حالة السوق · اكتمال البيانات · آخر تحديث
  'risk-card', // المخاطرة المستهلكة والمتبقية
  'profile-card', // الملف المختار والفعّال
  'decision-card', // القرار النهائي والنتيجة الحتمية
  // «no-trade-card» حُذفت عمداً: شرح الامتناع صعد إلى أعلى الشاشة بحجم
  // العنوان بدل أن يكون بطاقةً بين تسع. المعلومة تُفحَص بـ«no-trade-reason»
  // أدناه — والاختبار يجب أن يحرس **وجود السبب** لا وجود العلبة.
  'risk-week-card', // تفاصيل الأسبوع
  'strategy-card', // حالة الاستراتيجية
  'event-card', // الحدث القادم المهم
  'position-card', // المركز الحالي
];

describe('محتوى اللوحة', () => {
  beforeEach(() => {
    renderWithHarness(<HomeScreen />, { status: 'UNLOCKED' });
  });

  it.each(REQUIRED_CARDS)('البطاقة «%s» موجودة', (testID) => {
    expect(screen.getByTestId(testID)).toBeTruthy();
  });

  it('تعرض حالة النظام واتصال الوسيط وحالة السوق', () => {
    expect(screen.getByTestId('system-state-pill')).toBeTruthy();
    expect(screen.getByTestId('broker-field')).toBeTruthy();
    expect(screen.getByTestId('market-field')).toBeTruthy();
  });

  it('تعرض اكتمال البيانات وآخر تحديث', () => {
    expect(screen.getByTestId('completeness-field')).toBeTruthy();
    expect(screen.getByTestId('last-refresh-field')).toBeTruthy();
  });

  it('تعرض النتيجة الحتمية بعدد ونهاية سلّم', () => {
    const score = screen.getByTestId('score-field');
    expect(String(score.props.accessibilityLabel)).toContain('/');
  });

  it('تعرض سبب الامتناع بنصّ الخادم', () => {
    expect(screen.getByTestId('no-trade-reason')).toHaveTextContent(
      fixtures.status.no_trade_reason_ar!,
    );
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

  it('لا مركز مفتوح يُقال صراحةً لا يُترك فراغاً', () => {
    expect(screen.getByTestId('no-position')).toHaveTextContent(t.home.noPosition);
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
  it('في وضع التطوير تحمل الشاشة وسم «معاينة / Preview»', () => {
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
