/**
 * عناصر «الذكاء القريب» — ما يجب أن تقوله، لا كيف تبدو.
 *
 * الاختبارات هنا تحرس المعاني التي بُني عليها الاتجاه المعتمد: أنّ الصفر
 * المقيس يختلف عن المجهول، وأنّ الفجوة تُعلَن ولا تُخفى، وأنّ ما لا تتّخذه
 * استراتيجيةٌ لا يُحسب في أدائها.
 */
import React from 'react';
import { screen } from '@testing-library/react-native';

import { AgentCard } from '@/components/AgentCard';
import { DayPath } from '@/components/DayPath';
import { GapNote } from '@/components/GapNote';
import { SectionTitle } from '@/components/SectionTitle';
import { Tag, countsTowardStrategy, tagLabel } from '@/components/Tag';
import { Trio } from '@/components/Trio';
import { Welcome } from '@/components/Welcome';

import { renderWithHarness } from './helpers';

const wrap = (node: React.ReactElement): void => {
  renderWithHarness(node);
};

describe('الحكم قبل الرقم', () => {
  it('يعرض جملةً مكتملة لا كلمة', () => {
    wrap(<Welcome greeting="مساء الخير، مآثر" verdict="لا شيء يحتاجكِ اليوم." />);
    expect(screen.getByText('لا شيء يحتاجكِ اليوم.')).toBeTruthy();
    expect(screen.getByText('مساء الخير، مآثر')).toBeTruthy();
  });

  it('ينطقهما معاً لقارئ الشاشة', () => {
    wrap(<Welcome greeting="مآثر" verdict="أوقفتُ نفسي اليوم." testID="w" />);
    expect(screen.getByTestId('w').props.accessibilityLabel).toBe(
      'مآثر. أوقفتُ نفسي اليوم.',
    );
  });
});

describe('ما يفكر فيه الوكيل', () => {
  it('يحمل العنوان والفقرة والشرائح', () => {
    wrap(
      <AgentCard
        title="لم أدخل اليوم"
        body="فحصتُ أربع أدوات في ١٤٤ دورة."
        chips={[{ label: '١٤٤ دورة' }, { label: 'صفر إشارة', tone: 'caution' }]}
      />,
    );
    expect(screen.getByText('لم أدخل اليوم')).toBeTruthy();
    expect(screen.getByText('١٤٤ دورة')).toBeTruthy();
    expect(screen.getByText('صفر إشارة')).toBeTruthy();
  });

  it('بلا شرائح لا يعرض صفّاً فارغاً', () => {
    wrap(<AgentCard title="عنوان" body="متن" testID="a" />);
    expect(screen.getByTestId('a').props.accessibilityLabel).toBe('عنوان. متن');
  });
});

describe('مسار اليوم — أين توقّف بالأرقام', () => {
  const steps = [
    { label: 'فُحصت', count: '4', reached: true },
    { label: 'مؤهّلة', count: '3', reached: true },
    { label: 'إعداد', count: '0', reached: false },
    { label: 'إشارة', count: '0', reached: false },
    { label: 'نُفّذت', count: '0', reached: false },
  ];

  it('يعرض كل خطوةٍ برقمها', () => {
    wrap(<DayPath steps={steps} stopAt={2} note="توقّف عند الإعداد." />);
    expect(screen.getByText('فُحصت')).toBeTruthy();
    expect(screen.getByText('4')).toBeTruthy();
    expect(screen.getByText('توقّف عند الإعداد.')).toBeTruthy();
  });

  it('ينطق المسار كاملاً لا كأشرطة', () => {
    wrap(<DayPath steps={steps} stopAt={2} note="توقّف عند الإعداد." testID="f" />);
    const label = screen.getByTestId('f').props.accessibilityLabel as string;
    expect(label).toContain('فُحصت 4');
    expect(label).toContain('إعداد 0');
    expect(label).toContain('توقّف عند الإعداد.');
  });

  it('الشرطة ليست صفراً — المجهول يُكتب مجهولاً', () => {
    const unknown = steps.map((s) => ({ ...s, count: '—', reached: false }));
    wrap(
      <DayPath
        steps={unknown}
        stopAt={null}
        note="لا أعرف أين توقّف المسار."
        testID="f"
      />,
    );
    const label = screen.getByTestId('f').props.accessibilityLabel as string;
    expect(label).toContain('فُحصت —');
    expect(label).not.toContain('فُحصت 0');
  });
});

describe('ثلاثة أرقامٍ بلا رابعٍ يجمعها', () => {
  it('يعرض الثلاثة منفصلة', () => {
    wrap(
      <Trio
        tiles={[
          { label: 'استراتيجي', value: '−0.79', tone: 'negative' },
          { label: 'إداري', value: '−0.34', tone: 'negative' },
          { label: 'تشغيلي', value: '−0.01', tone: 'negative' },
        ]}
      />,
    );
    expect(screen.getByText('−0.79')).toBeTruthy();
    expect(screen.getByText('−0.34')).toBeTruthy();
    expect(screen.getByText('−0.01')).toBeTruthy();
    // ولا مجموع: −1.14 لا يقيس أداء استراتيجية.
    expect(screen.queryByText('−1.14')).toBeNull();
  });
});

describe('نسبةُ الصفقة', () => {
  it('الاستراتيجية وحدها تُحسب في الأداء', () => {
    expect(countsTowardStrategy('STRATEGY')).toBe(true);
    expect(countsTowardStrategy('ADMINISTRATIVE')).toBe(false);
    expect(countsTowardStrategy('COMMISSIONING')).toBe(false);
    expect(countsTowardStrategy('UNATTRIBUTED')).toBe(false);
  });

  it('لكل نسبةٍ اسمٌ عربيّ صريح', () => {
    expect(tagLabel('ADMINISTRATIVE')).toBe('إغلاق إداري');
    expect(tagLabel('UNATTRIBUTED')).toBe('بلا نسبة');
    wrap(<Tag kind="COMMISSIONING" />);
    expect(screen.getByText('تشغيلية')).toBeTruthy();
  });
});

describe('فجوة العقد تُعلَن', () => {
  it('تسمّي الحقل الناقص كي يُعرف ما يرفعها', () => {
    wrap(
      <GapNote
        title="فجوة عقد"
        body="يحتاجان decision_quality و execution_quality في TradeRecord."
        testID="g"
      />,
    );
    expect(screen.getByText('فجوة عقد')).toBeTruthy();
    expect(screen.getByTestId('g').props.accessibilityLabel).toContain(
      'decision_quality',
    );
  });
});

describe('عنوان القسم وحاشيته', () => {
  it('يعرض الحاشية على الطرف الآخر', () => {
    wrap(<SectionTitle title="كل المراكز" note="آخر مزامنة الآن" />);
    expect(screen.getByText('كل المراكز')).toBeTruthy();
    expect(screen.getByText('آخر مزامنة الآن')).toBeTruthy();
  });

  it('بلا حاشية لا يعرض فراغاً', () => {
    wrap(<SectionTitle title="المستويات" />);
    expect(screen.getByText('المستويات')).toBeTruthy();
  });
});
