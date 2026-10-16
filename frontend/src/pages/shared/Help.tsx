import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { BookOpen, Search } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Card, Empty, Notice, PageHead } from "../../components/ui";
import { ARTICLES, type Article } from "../../help/articles";

const text = (a: Article) => [a.title, a.summary, ...a.keywords, ...a.body.flatMap((b) => [b.h || "", b.p || "", ...(b.ul || [])])].join(" ").toLowerCase();

function ArticleView({ a }: { a: Article }) {
  const { t } = useI18n();
  return (
    <Card>
      <article className="article" lang="en">
        <h1 style={{ marginTop: 0 }}>{a.title}</h1>
        <p className="muted">{a.summary}</p>
        {a.body.map((b, i) => (
          <section key={i}>
            {b.h && <h2>{b.h}</h2>}
            {b.p && <p>{b.p}</p>}
            {b.ul && <ul>{b.ul.map((x) => <li key={x}>{x}</li>)}</ul>}
          </section>
        ))}
      </article>
      <p style={{ marginTop: 16 }}><Link to="/help">← {t("help.all")}</Link></p>
    </Card>
  );
}

export function Help() {
  const { slug } = useParams();
  const { me } = useAuth();
  const { t, locale } = useI18n();
  const [q, setQ] = useState("");
  const ws = me?.active?.workspace || "citizen";
  const article = slug ? ARTICLES.find((a) => a.slug === slug) : undefined;
  const results = useMemo(() => {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    const list = terms.length ? ARTICLES.filter((a) => terms.every((term) => text(a).includes(term))) : ARTICLES;
    const forMe = (a: Article) => a.workspaces === "all" || a.workspaces.includes(ws);
    return { mine: list.filter(forMe), other: list.filter((a) => !forMe(a)) };
  }, [q, ws]);
  return (
    <>
      <PageHead title={t("help.title")} sub={t("help.sub")} />
      {locale !== "en" && <Notice kind="info">{t("help.englishOnly")}</Notice>}
      {slug && !article && <Notice kind="warning">{t("help.notFound")}</Notice>}
      {article ? <ArticleView a={article} /> : (
        <>
          <div className="row" style={{ margin: "16px 0" }}>
            <Search size={18} aria-hidden />
            <label className="sr-only" htmlFor="hq">{t("common.search")}</label>
            <input id="hq" type="search" className="input" style={{ maxWidth: 420 }} placeholder={t("help.searchPh")} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {results.mine.length + results.other.length === 0 && <Empty title={t("help.none")} icon={<BookOpen size={32} />} />}
          {results.mine.length > 0 && (
            <Card title={t("help.forYou", { ws: t(`workspace.${ws}`) })}>
              <ul className="list">{results.mine.map((a) => <li key={a.slug}><Link to={`/help/${a.slug}`}><b>{a.title}</b></Link><div className="small muted">{a.summary}</div></li>)}</ul>
            </Card>
          )}
          {results.other.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <Card title={t("help.otherRoles")}>
                <ul className="list">{results.other.map((a) => <li key={a.slug}><Link to={`/help/${a.slug}`}>{a.title}</Link><div className="small muted">{a.summary}</div></li>)}</ul>
              </Card>
            </div>
          )}
        </>
      )}
    </>
  );
}
