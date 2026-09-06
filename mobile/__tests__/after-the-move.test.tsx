/**
 * ما انتقل من «اليوم» وصل إلى تبويبه — ولم يسقط في الطريق.
 *
 * ## لماذا هذا الملف
 *
 * نقلُ عشر بطاقاتٍ من شاشةٍ إلى شاشتين يُسقِط الحراسة معه إن لم تُنقل:
 * اختبارُ «اللوحة تعرض حالة النظام» يصير خضراء بحذفه، والمعلومةُ تكون قد
 * ضاعت وأحدٌ لا يعلم. فالحراسةُ تتبع المحتوى ولا تُرفع.
 *
 * وهذا هو النمطُ نفسه الذي لاحقناه في الخادم طوال العمل، معكوساً: هناك
 * وحدةٌ سليمةٌ غيرُ مُركَّبة، وهنا حراسةٌ سليمةٌ تُترك بلا ما تحرسه.
 */
import { screen } from '@testing-library/react-native';

import PositionScreen from '../app/(app)/position';
import SystemScreen from '../app/(app)/system';
import { renderWithHarness } from './helpers';

jest.mock('@/api/config', () => ({
  ...jest.requireActual('@/api/config'),
  PREVIEW_DATA_ENABLED: true,
}));

describe('النظام — ما نزل إليه من «اليوم»', () => {
  beforeEach(() => {
    renderWithHarness(<SystemScreen />, { status: 'UNLOCKED' });
  });

  it('«حالة التشغيل» بطاقةٌ واحدة لا شظايا', () => {
    /*
      كانت مبعثرة: القاطعُ في أسفل هذه الشاشة، والخدمةُ والإيقاف في
      «اليوم». وسؤالُ «هل الوكيل سليم؟» يُجاب بنظرةٍ واحدة أو لا يُجاب.
    */
    expect(screen.getByTestId('operating-card')).toBeTruthy();
    expect(screen.getByTestId('system-state-pill')).toBeTruthy();
    expect(screen.getByTestId('operating-entry')).toBeTruthy();
    expect(screen.getByTestId('operating-killswitch')).toBeTruthy();
  });

  it('**نطاقُ الإيقاف يُقال** — يمنع الدخول ولا يوقف المراقبة', () => {
    expect(screen.getByTestId('operating-scope')).toHaveTextContent(/الدخول الجديد/);
  });

  it('حالةُ السوق واكتمالُ البيانات وآخرُ قراءة — كلُّها وصلت', () => {
    expect(screen.getByTestId('source-card')).toBeTruthy();
    expect(screen.getByTestId('market-field')).toBeTruthy();
    expect(screen.getByTestId('completeness-field')).toBeTruthy();
    expect(screen.getByTestId('last-refresh-field')).toBeTruthy();
  });

  it('**الأرصدة الثلاثة هنا، ومعها الجملةُ التي تمنع سوء القراءة**', () => {
    /*
      «الرصيد التجريبي ليس رأس المال» ليس زخرفاً: بدونه يُقرأ رصيدُ
      الوسيط الضخم على أنه ما تُحسب عليه الحدود — وهو ليس كذلك.
    */
    expect(screen.getByTestId('equity-baseline')).toBeTruthy();
    expect(screen.getByTestId('equity-current')).toBeTruthy();
    expect(screen.getByTestId('equity-broker')).toBeTruthy();
    expect(screen.getByTestId('demo-balance-note')).toBeTruthy();
  });

  it('الملفُّ والاستراتيجيةُ والحدثُ وصلوا، ومعهم صفُّ الملفّات', () => {
    expect(screen.getByTestId('profile-card')).toBeTruthy();
    expect(screen.getByTestId('strategy-card')).toBeTruthy();
    expect(screen.getByTestId('event-card')).toBeTruthy();
    expect(screen.getByTestId('nav-profiles')).toBeTruthy();
  });
});

describe('المحفظة — الثلاثيّ والحدود', () => {
  beforeEach(() => {
    renderWithHarness(<PositionScreen />, { status: 'UNLOCKED' });
  });

  it('**«الحماية» ثالثُ الثلاثي** — الإجابةُ الموجبة تُقال', () => {
    /*
      كانت الحمايةُ تُقال ببانرٍ يظهر عند العطل وحده. وغيابُ الإجابة
      الموجبة ليس مثلَ حضورها: الصمتُ يُقرأ اطمئناناً.
    */
    const trio = screen.getByTestId('position-trio');
    expect(trio).toBeTruthy();
    expect(trio).toHaveTextContent(/الحماية/);
    expect(trio).toHaveTextContent(/\d+\/\d+/);
  });

  it('الحدودُ نزلت إلى تبويبها', () => {
    expect(screen.getByTestId('limits-card')).toBeTruthy();
    expect(screen.getByTestId('limit-open-positions')).toBeTruthy();
    expect(screen.getByTestId('limit-entry-orders')).toBeTruthy();
    expect(screen.getByTestId('limit-consecutive-losses')).toBeTruthy();
    expect(screen.getByTestId('limit-absolute-loss')).toBeTruthy();
  });

  it('الأسبوعُ نزل معها', () => {
    expect(screen.getByTestId('risk-week-card')).toBeTruthy();
  });

  it('المخاطرةُ المفتوحة عند الوقف ما زالت تُجمَع', () => {
    expect(screen.getByTestId('total-risk')).toBeTruthy();
    expect(screen.getByTestId('total-exposure')).toBeTruthy();
  });
});
