'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { REPO_URL } from '@/lib/env';

const LINKS = [
  { href: '/method/', label: 'Method' },
  { href: '/docs/', label: 'API' },
  { href: '/for-listing-sites/', label: 'For listing sites' },
];

export function Brand() {
  return (
    <Link href="/" className="brand" aria-label="Hush IQ, home">
      <img src="/hushiq-logo-512.png" alt="" width={30} height={30} />
      Hush IQ
    </Link>
  );
}

export function SiteNav() {
  const path = usePathname();
  return (
    <header className="nav">
      <div className="wrap">
        <Brand />
        <nav className="nav-links" aria-label="Main">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} aria-current={path === l.href ? 'page' : undefined}>
              {l.label}
            </Link>
          ))}
          <a href={REPO_URL} target="_blank" rel="noreferrer">
            GitHub
          </a>
          <Link href="/#demo" className="nav-cta">
            Try a listing
          </Link>
        </nav>
      </div>
    </header>
  );
}
