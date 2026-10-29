import Link from 'next/link';

import { REPO_URL } from '@/lib/env';

import { Brand } from './site-nav';

export function SiteFooter() {
  return (
    <footer className="footer">
      <div className="wrap">
        <div>
          <Brand />
          <p>A noise score for any NYC apartment, for the way you sleep. Built on eight public city datasets and a Meta model that reads the listing.</p>
          <p>
            The noise model predates the Meta Global AI Developer Hackathon (Oct 26 to Nov 4, 2026). The listing reader, the verdict writer, engine v2 and
            this site were built during it. <a href={`${REPO_URL}/blob/main/HACKATHON.md`}>HACKATHON.md</a> draws the line.
          </p>
        </div>
        <div>
          <h4>Product</h4>
          <ul>
            <li><Link href="/#demo">Try a listing</Link></li>
            <li><Link href="/method/">How it’s worked out</Link></li>
            <li><Link href="/for-listing-sites/">For listing sites</Link></li>
          </ul>
        </div>
        <div>
          <h4>Build</h4>
          <ul>
            <li><Link href="/docs/">API docs</Link></li>
            <li><a href={REPO_URL}>Source on GitHub</a></li>
            <li><a href="https://hush-iq-api.vercel.app/docs">Score API (OpenAPI)</a></li>
          </ul>
        </div>
      </div>
    </footer>
  );
}
