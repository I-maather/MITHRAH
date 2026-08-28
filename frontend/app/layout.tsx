import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "متداول مآثر الذاتي",
  description: "نظام تداول ذاتي شخصي — عرض بتوقيت الرياض",
};

const NAV = [
  { href: "/", label: "لوحة اليوم" },
  { href: "/broker", label: "الوسيط" },
  { href: "/opportunities", label: "الفرص" },
  { href: "/trades", label: "الصفقات" },
  { href: "/risk", label: "المخاطر" },
  { href: "/strategies", label: "الاستراتيجيات" },
  { href: "/audit", label: "السجل" },
  { href: "/health", label: "صحة النظام" },
  { href: "/settings", label: "الإعدادات" },
] as const;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl">
      <body>
        <div className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-4 py-6 md:px-8">
          <header className="flex flex-col gap-4 border-b border-line pb-5 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-lg font-semibold">متداول مآثر الذاتي</h1>
                <span className="pill bg-amber-50 text-warn">بيئة تجريبية · DEMO</span>
              </div>
              <p className="mt-1 text-xs text-ink-faint">
                استخدام شخصي — ليس خدمة استشارات مالية. جميع الأوقات بتوقيت الرياض.
              </p>
            </div>
            <nav className="flex flex-wrap gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-full px-3 py-1.5 text-sm text-ink-soft transition hover:bg-surface hover:text-ink"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </header>
          <main className="flex-1">{children}</main>
          <footer className="border-t border-line pt-4 text-xs text-ink-faint">
            التداول الحقيقي مقفل في الكود وفي الإعدادات. لا يمكن تعديل دستور المخاطر ولا تبديل وضع المخاطرة من هذه الواجهة.
          </footer>
        </div>
      </body>
    </html>
  );
}
