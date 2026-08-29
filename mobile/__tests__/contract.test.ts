import { readFileSync } from 'fs';
import { join } from 'path';

import { fixtures } from '@/fixtures';

/**
 * الطرف الثاني من العقد.
 *
 * `docs/mobile-contract.json` هو الشكل المرجعي، ويُفحَص من الجهتين:
 *
 *     backend/tests/test_mobile_contract.py  ⇐ الخادم يُنتج كل مفتاح
 *     هذا الملف                              ⇐ بيانات العميل ما زالت تطابقه
 *
 * فتغييرُ أحد الطرفين وحده يُسقط اختباراً. وهذا ما كان ناقصاً حين انهار
 * التطبيق إلى شاشة سوداء: الخادم كان يرسل `kill_switch_active` والتطبيق
 * يقرأ `kill_switch.active`، وكلٌّ منهما مُختبَر وحده فمرّا معاً.
 */

type Shape = string | Shape[] | { [key: string]: Shape };

const CONTRACT = JSON.parse(
  readFileSync(join(__dirname, '..', '..', 'docs', 'mobile-contract.json'), 'utf8'),
) as Record<string, Shape> & { __non_nullable_paths__: string[] };

const META = ['__comment_ar__', '__non_nullable_paths__'];

const shapeOf = (value: unknown): Shape => {
  if (value === null) return 'nullable';
  if (Array.isArray(value)) return value.length > 0 ? [shapeOf(value[0])] : ['unknown'];
  if (typeof value === 'object') {
    const out: Record<string, Shape> = {};
    for (const key of Object.keys(value as object).sort()) {
      out[key] = shapeOf((value as Record<string, unknown>)[key]);
    }
    return out;
  }
  return typeof value;
};

const sections = Object.keys(CONTRACT).filter((k) => !META.includes(k));

describe('عقد الجوال — الطرف الذي يقرأ', () => {
  it('يغطّي كل قسم تعرضه شاشة', () => {
    expect(sections.sort()).toEqual(Object.keys(fixtures).sort());
  });

  it.each(sections)('بيانات «%s» تطابق العقد حرفياً', (section) => {
    const actual = shapeOf((fixtures as Record<string, unknown>)[section]);
    expect(actual).toEqual(CONTRACT[section]);
  });

  it('**كل مسار لا يقبل null يشير إلى حقل موجود فعلاً**', () => {
    // قائمةٌ تحرس حقلاً غير موجود هي حارس على لا شيء.
    const missing = CONTRACT.__non_nullable_paths__.filter((path) => {
      const parts = path.split('.');
      const section = parts[0] ?? '';
      const rest = parts.slice(1);
      let node: unknown = (fixtures as Record<string, unknown>)[section];
      for (const raw of rest) {
        const key = raw.replace('[]', '');
        if (raw.endsWith('[]')) {
          const arr = (node as Record<string, unknown>)?.[key];
          node = Array.isArray(arr) ? arr[0] : undefined;
        } else {
          node = (node as Record<string, unknown>)?.[key];
        }
        if (node === undefined) return true;
      }
      return node === undefined;
    });
    expect(missing).toEqual([]);
  });
});
