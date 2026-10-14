"""(0.10.9.2) Map-wide questions as people write them about a real infrastructure: an outage said in other words
("unavailable", "goes away", "cannot be reached", "which products feel it"), a group asked by its software's name
("the bilby group"), the environments a group is in, what keeps its files in a store; a team named in two languages
on two pages; a table column saying where each row keeps its data; the software a host runs filed with it."""
from __future__ import annotations

import pytest

PFX = "zqx"


@pytest.mark.parametrize("question,intent", [
    ("If Quokka is unavailable, which sites are hit?", "impact"),
    ("Which products suffer when Bilby goes away?", "impact"),
    ("Ledger cannot be reached today. Which of our products feel it?", "impact"),
    ("Bilby stops answering. What breaks as a result?", "impact"),
    ("Which host group is Quokka installed on?", "placement"),
    ("Which collections hold the Bilby backend?", "placement"),
    ("In which environments is the quokka group deployed?", "environments"),
    ("Which environments have a bilby group?", "environments"),
    ("Is bilby_web a production or a staging collection?", "environments"),
    ("Which sites store files in the Ledger store?", "callers"),
    ("Which hosts are in the quokka group?", "members"),
    ("Who looks after Quokka?", "owner"),
])
def test_the_kind_of_a_map_wide_question(question, intent):
    from supagent.knowledge.communities import intent_of

    assert intent_of(question) == intent


@pytest.mark.parametrize("a,b,want", [
    ("Ledger team", "équipe Ledger", "strong"),
    ("the Platform team", "l'équipe Plateforme", "typo"),
    ("Security crew", "équipe Sécurité", "typo"),
    ("Methods team", "équipe Méthodes", "typo"),
    ("Billing crew", "équipe Facturation", ""),        # another word: nothing to tell
    ("Billing team", "Building team", ""),
    ("Analytics team", "Analysts team", ""),
    ("Data team", "Date team", ""),
])
def test_a_team_named_in_two_languages_is_one_team(a, b, want):
    from supagent.knowledge.consolidate import same

    assert same(a, b, "team") == want


def _facts(text, title="Sites", parts=(), groups=()):
    from supagent.knowledge.understand import Names, discover, facts_of, norm

    n = Names()
    for p in parts:
        n.add_part(p)
    n.inventory_groups.update(norm(g) for g in groups)
    u = {"ukey": "p1", "path": "", "kind": "page", "title": title, "text": text, "meta": {}}
    u["found"] = discover(u)
    return {(f["subject"], f["verb"], f["obj"], f["obj_kind"]) for f in facts_of(u, None, n, {})}


def test_a_column_saying_where_a_row_keeps_its_data_names_the_stores_it_uses(ctx):
    text = ("Site | What it does | Run by | Keeps its data in\n"
            "Quokka | the update system | Tools crew | PostgreSQL, Amazon S3\n"
            "Bilby | the test results | Tools crew | MySQL\n")
    got = _facts(text, parts=("Quokka", "Bilby"))
    assert ("Quokka", "uses", "PostgreSQL", "database") in got and ("Bilby", "uses", "MySQL", "database") in got
    assert ("Quokka", "uses", "Amazon S3", "part") in got                # a cloud provider's service: outside
    assert ("Amazon S3", "is_a", "external", "kind") in got
    assert not any(o == "PostgreSQL" and v == "is_a" for _s, v, o, _k in got)


def test_the_software_a_host_runs_by_its_name():
    from supagent.knowledge.naming import kind_of
    from supagent.knowledge.projects import _nested

    assert kind_of("monit") == "monitoring" and kind_of("jumpbox") == "infrastructure"
    assert kind_of("composer") == "runtime" and kind_of("php") == "runtime" and kind_of("java") == "runtime"
    assert kind_of("python") is None and kind_of("monitor-ledger") is None
    assert _nested("software/quokka/quokka-app") == "quokka" and _nested("bilby/app") == "bilby"


def test_a_runtime_role_is_the_hosts_software_only_where_the_person_files_it(ctx, monkeypatch):
    from supagent.knowledge import naming
    from supagent.knowledge.projects import Role

    monkeypatch.setattr(naming, "software_category", lambda: None)
    assert Role("acme.php", None).part is None and Role("acme.java", None).part is None
    monkeypatch.setattr(naming, "software_category", lambda: "server software")
    assert Role("acme.php", None).part == "php" and Role("acme.java", None).part == "java"
    assert Role("acme.python", None).part is None and Role("acme.pip", None).part is None   # the system's own


def _clean(db):
    from supagent.models import Facet, Link

    db.session.rollback()
    ids = [i for (i,) in db.session.query(Facet.id).filter(Facet.value.ilike(PFX + "%"))]
    refs = [f"facet:{i}" for i in ids]
    if ids:
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()


@pytest.fixture()
def estate(ctx, monkeypatch):
    """A search engine (software) running on its group in two environments, each group with its hosts; a shop of
    one web part that uses the engine and writes its files to a store."""
    from superset.extensions import db

    from supagent import settings

    real = settings.get
    monkeypatch.setattr(settings, "get",
                        lambda key: ["server", "environment"] if key == "categories.custom" else real(key))

    from supagent.knowledge.facets import PART_OF
    from supagent.knowledge.freshness import touch
    from supagent.models import Facet, Link

    _clean(db)
    v = {}
    for cat, name in (("component", "search"), ("server", "search (ops prod)"), ("server", "search (ops stg)"),
                      ("server", "vm-p1"), ("server", "vm-p2"), ("server", "vm-s1"), ("environment", "ops prod"),
                      ("environment", "ops stg"), ("application", "shop"), ("component", "shop-web"),
                      ("component", "files")):
        f = Facet(facet=cat, value=f"{PFX}-{name}", status="approved", source="admin")
        db.session.add(f)
        db.session.flush()
        v[name] = f.id

    def link(a, kind, b):
        db.session.add(Link(a_ref=f"facet:{v[a]}", b_ref=f"facet:{v[b]}", kind=kind, status="approved", source="admin"))

    link("vm-p1", PART_OF, "search (ops prod)")
    link("vm-p2", PART_OF, "search (ops prod)")
    link("vm-s1", PART_OF, "search (ops stg)")
    link("search (ops prod)", PART_OF, "ops prod")
    link("search (ops stg)", PART_OF, "ops stg")
    link("search", "runs_on", "search (ops prod)")
    link("search", "runs_on", "search (ops stg)")
    link("shop-web", PART_OF, "shop")
    link("shop-web", "depends_on", "search")
    link("shop-web", "sends_to", "files")
    db.session.commit()
    touch()
    yield v
    _clean(db)


@pytest.mark.parametrize("question,want", [
    (f"Which hosts are in the {PFX}-search group?", {f"{PFX}-vm-p1", f"{PFX}-vm-p2", f"{PFX}-vm-s1"}),
    (f"In which environments is the {PFX}-search group deployed?", {f"{PFX}-ops prod", f"{PFX}-ops stg"}),
    (f"If {PFX}-search is unavailable, which systems are hit?", {f"{PFX}-shop"}),
    (f"Which systems keep their files in {PFX}-files?", {f"{PFX}-shop"}),
    (f"Where is {PFX}-search deployed?", {f"{PFX}-search (ops prod)", f"{PFX}-search (ops stg)"}),   # no parts of its
    (f"On which host groups does {PFX}-search run?", {f"{PFX}-search (ops prod)", f"{PFX}-search (ops stg)"}),   # own
    (f"What runs on the {PFX}-search (ops prod) group?", {f"{PFX}-search"}),
])
def test_map_wide_questions_written_as_people_do(estate, question, want):
    from supagent.knowledge.communities import overview

    assert set(overview(question)["answer"]) == want


@pytest.fixture()
def crews(ctx, monkeypatch):
    """Two teams named on the map in French only, each owning a service."""
    from superset.extensions import db

    from supagent import settings

    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: ["team"] if key == "categories.custom" else real(key))

    from supagent.knowledge.freshness import touch
    from supagent.knowledge.sysmap import worded
    from supagent.models import Facet, Link

    _clean(db)
    v = {}
    for cat, name in (("team", "équipe Sécurité"), ("team", "équipe Plateforme"), ("application", f"{PFX}-ledger"),
                      ("application", f"{PFX}-quokka")):
        f = Facet(facet=cat, value=name, status="approved", source="admin")
        db.session.add(f)
        db.session.flush()
        v[name] = f.id
    for a, b in ((f"{PFX}-ledger", "équipe Sécurité"), (f"{PFX}-quokka", "équipe Plateforme")):
        db.session.add(Link(a_ref=f"facet:{v[a]}", b_ref=f"facet:{v[b]}", kind=worded("owned by"), status="approved",
                            source="admin", note="owned by"))
    db.session.commit()
    touch()
    yield v
    db.session.rollback()
    from supagent.models import Facet as F, Link as L

    ids = list(v.values())
    refs = [f"facet:{i}" for i in ids]
    db.session.query(L).filter(L.a_ref.in_(refs) | L.b_ref.in_(refs)).delete(synchronize_session=False)
    db.session.query(F).filter(F.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()


def test_a_team_asked_in_english_found_by_its_french_name(crews):
    from supagent.knowledge.communities import overview

    got = overview("What is the Security crew responsible for?")
    assert got["anchors"] == ["équipe Sécurité"] and got["answer"] == [f"{PFX}-ledger"]
    assert overview("Which applications does the Platform team look after?")["answer"] == [f"{PFX}-quokka"]
    assert overview("What does the Billing team own?")["answer"] == []      # no such team: nothing
