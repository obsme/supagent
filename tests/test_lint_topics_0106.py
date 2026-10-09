"""(0.10.6) A topic and a server or a group of one name ("monitoring": the subject and the inventory's group) are two
things, which the classification keeps apart: To review does not warn of them; a part and a server of one name still
are one name for two things."""

from __future__ import annotations


def test_a_topic_and_a_server_of_one_name_are_no_warning(app):
    from superset.extensions import db

    from supagent.knowledge import lint as L
    from supagent.models import Facet

    with app.app_context():
        made = [Facet(facet="server", value="zqmon", status="approved", source="docs"),
                Facet(facet="subject", value="zqmon", status="proposed", source="llm"),
                Facet(facet="server", value="zqweb", status="approved", source="docs"),
                Facet(facet="application", value="zqweb", status="proposed", source="docs")]
        db.session.add_all(made)
        db.session.commit()
        try:
            got = {(w["kind"], w["subject"].lower()) for w in L.same_name()}
            assert ("same_name", "zqmon") not in got
            assert ("same_name", "zqweb") in got
        finally:
            for x in made:
                db.session.delete(x)
            db.session.commit()
