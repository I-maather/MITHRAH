/**
 * حكمُ اليوم — وأخطرُ ما يحرسه: ألّا يُقرأ الجهل صمتاً.
 */
import { dayVerdict, greetingFor } from '@/utils/verdict';

const base = {
  killSwitchActive: false,
  unknown: false,
  locallyPaused: false,
  openPositions: 0,
};

const noon = new Date('2026-09-05T09:00:00');

describe('حكم اليوم', () => {
  it('الصمت الطبيعي يُقال جملةً لا فراغاً', () => {
    expect(dayVerdict(base, noon).verdict).toBe('لا شيء يحتاجكِ اليوم.');
  });

  it('**الجهل يعلو الصمت** — انقطاعٌ لا يُقرأ «لا شيء»', () => {
    const v = dayVerdict({ ...base, unknown: true }, noon);
    expect(v.verdict).toBe('لا أعرف حالتي الآن.');
    expect(v.tone).toBe('caution');
  });

  it('وجهلٌ مع مراكز يبقى جهلاً — لا يُعلن عددٌ لا نثق به', () => {
    const v = dayVerdict({ ...base, unknown: true, openPositions: 5 }, noon);
    expect(v.verdict).toBe('لا أعرف حالتي الآن.');
  });

  it('قاطع الطوارئ يعلو كل شيء', () => {
    const v = dayVerdict(
      { killSwitchActive: true, unknown: true, locallyPaused: true, openPositions: 4 },
      noon,
    );
    expect(v.verdict).toBe('أوقفتُ نفسي اليوم.');
    expect(v.tone).toBe('negative');
  });

  it('المراكز تُعدّ بصيغتها العربية', () => {
    expect(dayVerdict({ ...base, openPositions: 1 }, noon).verdict).toBe(
      'مركزٌ واحد مفتوح.',
    );
    expect(dayVerdict({ ...base, openPositions: 2 }, noon).verdict).toBe(
      'مركزان مفتوحان.',
    );
    expect(dayVerdict({ ...base, openPositions: 5 }, noon).verdict).toBe(
      '5 مراكز مفتوحة.',
    );
  });

  it('الإيقاف بقرار المالكة يُقال بلا لوم', () => {
    const v = dayVerdict({ ...base, locallyPaused: true }, noon);
    expect(v.verdict).toBe('الدخول موقوفٌ بقرارك.');
  });

  it('عددٌ غير معروف لا يُقرأ صفراً ولا يُعلَن مركزاً', () => {
    const v = dayVerdict({ ...base, openPositions: null }, noon);
    expect(v.verdict).toBe('لا شيء يحتاجكِ اليوم.');
  });
});

describe('التحيّة بالوقت لا بالحالة', () => {
  it.each([
    [3, 'ليلة هادئة'],
    [8, 'صباح الخير'],
    [14, 'طاب يومك'],
    [21, 'مساء الخير'],
  ])('الساعة %i ⇒ %s', (hour, expected) => {
    expect(greetingFor(hour as number)).toBe(expected);
  });
});
