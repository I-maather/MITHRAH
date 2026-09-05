

jest.mock('@/api/config', () => ({
  ...jest.requireActual('@/api/config'),
  PREVIEW_DATA_ENABLED: false,
  TRADING_ENVIRONMENT: 'DEMO',
}));

import { screen } from '@testing-library/react-native';

import { EnvironmentBadge } from '@/components';
import {
  observeEnvironment,
  resetServerEnvironment,
  setServerEnvironment,
} from '@/api/environment';
import { renderWithHarness } from './helpers';

/**
 * «تجريبي أم حقيقي؟» — السؤال الوحيد الذي خطؤه لا يُستدرَك.
 *
 * كان جوابه تلميحاً بحجم 11pt بلونٍ ثالثي داخل البطاقة السادسة في ترتيب
 * التمرير. وصار شارةً في رأس كل شاشة تجمع مصدرين: ما بُني عليه التطبيق،
 * وأين يتداول الخادم الآن. **واختلافهما إنذارٌ لا تفصيل.**
 */

describe('شارة البيئة', () => {
  beforeEach(() => {
    resetServerEnvironment();
  });

  it('قبل أوّل استجابة تقول إنّ الخادم لم يُقرأ بعد — ولا تفترض', () => {
    renderWithHarness(<EnvironmentBadge />);
    expect(screen.getByTestId('environment-badge-note')).toBeTruthy();
    expect(
      screen.getByText('من إعلان البناء — لم تُقرأ حالة الوسيط من الخادم بعد.'),
    ).toBeTruthy();
  });

  it('حين يتّفق المصدران تقول «تجريبي» بلا ملاحظة', () => {
    setServerEnvironment('DEMO');
    renderWithHarness(<EnvironmentBadge />);
    expect(screen.getByText('تجريبي')).toBeTruthy();
    expect(screen.queryByTestId('environment-badge-note')).toBeNull();
  });

  it('**التعارض يُعرَض إنذاراً**: بناءٌ تجريبي وخادمٌ حقيقي', () => {
    setServerEnvironment('REAL');
    renderWithHarness(<EnvironmentBadge />);
    expect(screen.getByText('تعارضُ بيئة')).toBeTruthy();
    expect(
      screen.getByText('البناء تجريبي والخادم على حسابٍ حقيقي. أوقفي واستوثقي.'),
    ).toBeTruthy();
  });

  it('النصّ يحمل المعنى — لا اللون وحده', () => {
    setServerEnvironment('REAL');
    renderWithHarness(<EnvironmentBadge />);
    const pill = screen.getByTestId('environment-badge-pill');
    expect(String(pill.props.accessibilityLabel)).toContain('تعارضُ بيئة');
    expect(String(pill.props.accessibilityLabel)).toContain('أوقفي واستوثقي');
  });
});

describe('التقاط حالة الوسيط من الحمولة', () => {
  beforeEach(() => {
    resetServerEnvironment();
  });

  it('حمولةٌ بلا broker لا تُغيّر شيئاً — الغياب ليس خبراً', () => {
    observeEnvironment({ anything: 1 });
    renderWithHarness(<EnvironmentBadge />);
    expect(screen.getByTestId('environment-badge-note')).toBeTruthy();
  });

  it('is_demo=false يُقرأ حقيقياً', () => {
    observeEnvironment({ broker: { is_demo: false } });
    renderWithHarness(<EnvironmentBadge />);
    expect(screen.getByText('تعارضُ بيئة')).toBeTruthy();
  });

  it('قيمةٌ غير منطقية تُتجاهَل بصمت', () => {
    observeEnvironment({ broker: { is_demo: 'yes' } });
    renderWithHarness(<EnvironmentBadge />);
    expect(screen.getByTestId('environment-badge-note')).toBeTruthy();
  });
});
