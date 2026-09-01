import { t } from '@/i18n';

/**
 * نظافة النصّ المعروض.
 *
 * ## العطل الذي فرض هذا الملف
 *
 * ستّ جملٍ في `ar.ts` كانت تحمل `**تشديداً**` بأسلوب Markdown — وليس في
 * التطبيق مُحلِّل Markdown. فما كان يصل إلى الشاشة هو النجمتان أنفسهما:
 * «الصمت هنا \*\*عملٌ وليس عطلاً\*\*». وكل اختبارات تلك الشاشات تمرّ، لأن
 * أياً منها يبحث عن جزءٍ من الجملة لا عن شكلها.
 *
 * وهي الصورة نفسها للعطل الحاكم: علامةٌ كُتبت لقارئ المصدر وظهرت للمستخدم،
 * لأن أحداً لم يقرأ الناتج بعينه.
 */

const strings = (node: unknown, path: string, out: Array<[string, string]>): void => {
  if (typeof node === 'string') {
    out.push([path, node]);
    return;
  }
  if (Array.isArray(node)) {
    node.forEach((item, i) => strings(item, `${path}[${i}]`, out));
    return;
  }
  if (typeof node === 'object' && node !== null) {
    for (const [key, value] of Object.entries(node)) {
      strings(value, path === '' ? key : `${path}.${key}`, out);
    }
  }
};

const all: Array<[string, string]> = [];
strings(t, '', all);

describe('نصوص الواجهة', () => {
  it('ليست فارغة — وإلا لم يكن هذا الفحص يفحص شيئاً', () => {
    expect(all.length).toBeGreaterThan(200);
  });

  it('لا علامة Markdown في نصٍّ يُعرض — فلا مُحلِّل لها', () => {
    const leaking = all.filter(([, value]) => /\*\*|__|`/.test(value)).map(([path]) => path);
    expect(leaking).toEqual([]);
  });

  it('لا نصّ يدّعي أن التطبيق ينفّذ', () => {
    // الحدّ الذي يقوم عليه المشروع كلّه: التطبيق يقرأ ويوقف، ولا يفتح.
    const claims = all
      .filter(([, v]) => /اضغطي للشراء|نفّذ الأمر|افتحي صفقة/.test(v))
      .map(([path]) => path);
    expect(claims).toEqual([]);
  });
});
