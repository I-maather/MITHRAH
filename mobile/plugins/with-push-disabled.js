/**
 * ملحق: إزالة استحقاق APNs عند تعطيل الإشعارات.
 *
 * ## لماذا لا يكفي حذفه من `app.config.ts`
 *
 * `expo-notifications` تُربَط تلقائياً (autolinking) بمجرّد وجودها في
 * `dependencies`، ويعمل ملحقها **سواء أُدرج في `plugins` أم لم يُدرج**.
 * وهو يحقن `aps-environment` في الاستحقاقات بنفسه.
 *
 * قيسَ ذلك ولم يُفترَض: بعد إزالة الملحق من `plugins` وإزالة `entitlements`
 * من كتلة `ios`، أظهر `expo config --type introspect` أن الاستحقاق **ما زال
 * موجوداً**.
 *
 * ## لماذا يهمّ
 *
 *     Personal development teams do not support the Push Notifications
 *     capability.
 *
 * الحساب المجاني لا يُصدر ملف تزويد يحمل هذا الاستحقاق. فوجودُه يمنع تشغيل
 * التطبيق على الجهاز أصلاً — بسبب ميزة معطّلة لن تعمل قبل عضوية مدفوعة.
 * الحذف اليدوي من Xcode لا يدوم: `prebuild --clean` يعيد توليد `ios/`.
 *
 * فهذا الملحق يعمل **بعد** الجميع، ويحذف ما حقنه غيره.
 */
const { withEntitlementsPlist } = require('@expo/config-plugins');

const withPushDisabled = (config) =>
  withEntitlementsPlist(config, (cfg) => {
    delete cfg.modResults['aps-environment'];
    return cfg;
  });

module.exports = withPushDisabled;
