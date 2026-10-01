import Link from "next/link";
import { ArrowRight, Check, CheckCheck, FileCheck2, Fingerprint, Layers3, LockKeyhole, ShieldCheck, Sparkles, Users } from "lucide-react";

export function LandingPage() {
  return <div className="marketing">
    <a className="skip-link" href="#product">Skip to product</a>
    <header className="marketing-nav">
      <Link href="/" className="marketing-brand"><span className="brand-mark"><ShieldCheck size={22} /></span>ClaimGuard<span className="brand-dot">.</span></Link>
      <nav aria-label="Product navigation"><a href="#workflow">How it works</a><a href="#teams">For your team</a><a href="#trust">Built for trust</a></nav>
      <Link href="/workspace/home" className="marketing-signin">Open workspace <ArrowRight size={16} /></Link>
    </header>
    <main id="product">
      <section className="marketing-hero">
        <div className="hero-copy"><p className="marketing-kicker"><span /> Claim readiness, together</p><h1>Clarity before<br />every <span>claim.</span></h1>
          <p className="hero-description">Turn scattered checks into a clear next step. ClaimGuard brings evidence, review guidance, and your team into one connected workspace.</p>
          <div className="marketing-actions"><Link href="/workspace/home" className="marketing-primary">Enter your workspace <ArrowRight size={18} /></Link><a href="#workflow" className="marketing-secondary">Explore the workflow <span>↓</span></a></div>
          <p className="hero-footnote"><ShieldCheck size={16} /> Every finding explained. Every decision yours.</p>
        </div>
        <div className="product-preview" aria-label="Illustrative claim review example">
          <div className="preview-top"><span><ShieldCheck size={18} /> Claim review</span><span className="preview-example">Illustrative example</span></div>
          <div className="preview-body"><div className="preview-title"><div><small>OUTPATIENT CLAIM</small><h2>One claim. A clear path forward.</h2></div><span className="preview-status">Needs review</span></div>
            <div className="preview-steps"><span><Check size={13} /> Received</span><span><Check size={13} /> Checked</span><strong>03 &nbsp; In review</strong></div>
            <div className="preview-finding"><span className="preview-rule">R012</span><div><h3>The totals don’t match</h3><p>The billed total differs from the sum of service lines.</p></div></div>
            <div className="preview-evidence"><div><span>Billed total</span><strong>SAR 1,850</strong></div><div><span>Service line total</span><strong>SAR 1,800</strong></div><div><span>Difference</span><strong className="preview-difference">SAR 50</strong></div></div>
            <div className="preview-guidance"><Sparkles size={19} /><div><strong>A useful next step</strong><p>Compare the source invoice with the service lines. Correct the documented error, then recheck the claim.</p><small>Grounded in the finding and its evidence</small></div></div>
            <div className="preview-bottom"><span><Fingerprint size={16} /> Original evidence preserved</span><span className="preview-action">Review → correct → recheck</span></div>
          </div>
          <div className="preview-receipt"><span><CheckCheck size={20} /></span><div><strong>A record you can follow</strong><small>Checks, corrections, and decisions stay connected.</small></div></div>
        </div>
      </section>
      <div className="marketing-principles"><span>Built around your review process</span><p><FileCheck2 size={19} /> Rule-linked findings</p><p><Sparkles size={19} /> Evidence-grounded guidance</p><p><Users size={19} /> Human oversight</p><p><Fingerprint size={19} /> Traceable decisions</p></div>
      <section className="marketing-workflow" id="workflow"><div className="marketing-section-intro"><p className="marketing-kicker">A connected review process</p><h2>From “what’s wrong?”<br />to “here’s what’s next.”</h2><p>One place to understand an issue, coordinate the response, and verify the correction.</p></div>
        <ol className="workflow-story"><li><span>01</span><div><h3>Bring the claim into focus</h3><p>Start with structured claim data. Consistent checks surface missing information, conflicting dates, duplicates, and amount mismatches.</p></div></li><li><span>02</span><div><h3>Understand the finding</h3><p>See the rule, the exact source values, and a plain-language next step. AI assistance stays grounded in what the checks found.</p></div></li><li><span>03</span><div><h3>Move forward with confidence</h3><p>Request information, record a decision, or correct a documented error. Recheck a new version while keeping the original intact.</p></div></li></ol>
      </section>
      <section className="marketing-teams" id="teams"><div className="marketing-section-intro"><p className="marketing-kicker">One clinic. A coordinated team.</p><h2>Everyone knows<br />their next move.</h2><p>Clear ownership and role-based access keep claim review moving.</p><Link href="/workspace/home">Find your workspace <ArrowRight size={18} /></Link></div><div className="team-stories">
        <article><span>RCM REVIEWERS</span><h3>A focused queue.<br />Answers within reach.</h3><p>Work assigned claims with findings, evidence, and correction guidance side by side.</p><div className="team-capabilities"><span>My Queue</span><span>Requests</span><span>Rechecks</span></div></article>
        <article><span>RCM LEADS</span><h3>See the workload.<br />Keep review moving.</h3><p>Route claims to reviewers, handle escalations, and follow the team’s review activity.</p><div className="team-capabilities"><span>Team Queue</span><span>Assignments</span><span>Review Quality</span></div></article>
        <article><span>CLINIC ADMINS</span><h3>Your clinic,<br />clearly in view.</h3><p>Manage departments and access, organize ownership, and monitor clinic-wide activity.</p><div className="team-capabilities"><span>Overview</span><span>Team &amp; Access</span><span>Analytics</span></div></article>
      </div></section>
      <section className="marketing-trust" id="trust"><div><p className="marketing-kicker">Trust is part of the workflow</p><h2>Useful intelligence.<br /><span>Accountable decisions.</span></h2></div><div className="trust-details"><p><ShieldCheck /><span><strong>Consistent checks come first</strong>AI guidance cannot change a deterministic rule outcome.</span></p><p><LockKeyhole /><span><strong>A workspace for each clinic</strong>Clinic boundaries and roles control who can see and act on claims.</span></p><p><Layers3 /><span><strong>History stays connected</strong>Corrections create new versions, backed by a tamper-evident audit trail.</span></p></div></section>
      <section className="marketing-cta"><div><p className="marketing-kicker">Give every claim a clearer next step</p><h2>Make review work for your team.</h2></div><Link href="/workspace/home" className="marketing-primary">Open ClaimGuard <ArrowRight size={18} /></Link></section>
    </main>
    <footer className="marketing-footer"><Link className="marketing-brand" href="/"><ShieldCheck size={22} />ClaimGuard.</Link><p>Clarity before every claim.</p><span>Pilot workspace · Synthetic data<br />Administrative review support. No automatic payer submission.</span></footer>
  </div>;
}
