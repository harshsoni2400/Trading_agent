"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Live Trading" },
  { href: "/backtest", label: "Backtesting" },
  { href: "/optimizer", label: "Optimizer" },
  { href: "/chat", label: "Chat" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <nav className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center gap-6">
      <span className="font-bold text-lg text-blue-400 mr-4">Trading Bot</span>
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className={`text-sm font-medium transition-colors ${
            pathname === link.href
              ? "text-white border-b-2 border-blue-500 pb-1"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
