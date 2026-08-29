import { fireEvent, render, screen } from '@testing-library/react-native';
import React from 'react';
import { Text } from 'react-native';

import { CrashGuard } from '@/components';

/**
 * الشاشة السوداء لن تعود.
 *
 * انهار التصيير مرة، فلم يبقَ على الشاشة شيء ولا رسالة. هذه الاختبارات
 * تحرس البديل: رسالة عربية، وطمأنة صريحة أن التطبيق لا يأذن بتنفيذ،
 * وزرّ يعيد المحاولة — وألّا يتسرّب نصّ الخطأ في الإصدار المنشور.
 */

const Boom = ({ explode }: { explode: boolean }): React.JSX.Element => {
  if (explode) {
    // نفس شكل العطب الحقيقي: قراءة حقل داخل شيء غير موجود.
    const missing = undefined as unknown as { active: boolean };
    return <Text>{String(missing.active)}</Text>;
  }
  return <Text testID="fine">بخير</Text>;
};

describe('حارس الانهيار', () => {
  const silence = (): void => {
    jest.spyOn(console, 'error').mockImplementation(() => undefined);
  };

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('لا يتدخّل ما دام كل شيء سليماً', () => {
    render(
      <CrashGuard>
        <Boom explode={false} />
      </CrashGuard>,
    );
    expect(screen.getByTestId('fine')).toBeTruthy();
  });

  it('**يعرض رسالة بدل شاشة سوداء** عند انهيار التصيير', () => {
    silence();
    render(
      <CrashGuard>
        <Boom explode />
      </CrashGuard>,
    );
    expect(screen.getByTestId('crash-guard')).toBeTruthy();
    expect(screen.getByTestId('crash-guard-body')).toBeTruthy();
  });

  it('**يقول أولاً إن التطبيق لا يأذن بتنفيذ**', () => {
    silence();
    render(
      <CrashGuard>
        <Boom explode />
      </CrashGuard>,
    );
    expect(screen.getByTestId('crash-guard-safety')).toHaveTextContent(
      /لا يأذن بتنفيذ/,
    );
  });

  it('يمرّر الخطأ للتسجيل ولا يبتلعه صامتاً', () => {
    silence();
    const onError = jest.fn();
    render(
      <CrashGuard onError={onError}>
        <Boom explode />
      </CrashGuard>,
    );
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);
  });

  it('**لا يعرض نصّ الخطأ في الإصدار المنشور**', () => {
    silence();
    render(
      <CrashGuard showDetail={false}>
        <Boom explode />
      </CrashGuard>,
    );
    expect(screen.queryByTestId('crash-guard-detail')).toBeNull();
  });

  it('زرّ إعادة المحاولة يعيد التصيير', () => {
    silence();
    const { rerender } = render(
      <CrashGuard>
        <Boom explode />
      </CrashGuard>,
    );
    expect(screen.getByTestId('crash-guard')).toBeTruthy();

    rerender(
      <CrashGuard>
        <Boom explode={false} />
      </CrashGuard>,
    );
    fireEvent.press(screen.getByTestId('crash-guard-retry'));
    expect(screen.getByTestId('fine')).toBeTruthy();
  });
});
