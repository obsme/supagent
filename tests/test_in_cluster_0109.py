"""(0.10.9) A scrape job named after a part runs on the hosts it scrapes, but a Kubernetes service's own name
(<service>.<namespace>.svc, .svc.cluster.local) is that service, no host: once the job's name was approved, a second
learning proposed "collector.platform.svc.cluster.local" as a server the collector runs on."""

from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_second_pass_0105 import _clean, _repo, _state

REPO = {"prometheus/prometheus.yml": "scrape_configs:\n  - job_name: zqcollector\n    static_configs:\n"
                                     "      - targets: ['zqcollector.zqns.svc.cluster.local:8889']\n"
                                     "  - job_name: zqagent\n    static_configs:\n      - targets: ['zqhost-9:9100']\n"
                                     "  - job_name: zqcache\n    static_configs:\n      - targets: ['zqcache.zqns.svc:9121']\n"}


def test_a_kubernetes_service_name_is_no_host_a_job_runs_on(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.models import Facet

    known = [Facet(facet="application", value=v, status="approved", source="admin")
             for v in ("zqcollector", "zqagent", "zqcache")]
    db.session.add_all(known)
    db.session.commit()
    before, d = _state(), _repo(REPO, name="zqmon")
    try:
        U.run(reason="test")
        rels = {(r["from"], r["kind"], r["to"]) for r in U.export()["relations"]}
        assert ("zqagent", "runs_on", "zqhost-9") in rels                   # a host: where the job's part runs
        assert not any(k == "runs_on" and ".svc" in b for _a, k, b in rels)  # a service's name: no host
    finally:
        _clean(before, [d])
        db.session.query(Facet).filter(Facet.id.in_([f.id for f in known])).delete(synchronize_session=False)
        db.session.commit()
