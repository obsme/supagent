"""(0.10.4) The learning's third round: a workload versioned after its application (details-v1 of app details) is
that application, a templated manifest is read, an address variable's default in code is a call, a role applying
manifests is no part, a Compose network alias is another name; "routes the requests to", a request as a thing, the
verbs of other languages, "are stored in"; a public site named under no endpoint key, a download, an image's label,
a schema or a page to read are no endpoints."""
from __future__ import annotations

from test_prose_010 import facts
from test_projects_010 import triples, units


BOOK = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: details-v1
  labels: {app: details, version: v1}
spec:
  template:
    metadata:
      labels: {app: details, version: v1}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ratings-v2
  labels: {app: ratings, version: v2}
spec:
  template:
    spec:
      containers:
        - name: ratings
          env:
            - name: MONGO_DB_URL
              value: mongodb://mongodb:27017/test
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mongodb-v1
  labels: {app: mongodb, version: v1}
"""
TEMPLATED = """apiVersion: v1
kind: ConfigMap
metadata:
  name: site-config
  namespace: {{ ns }}
data:
  SITE_DATABASE_HOST: 'mysql.site.svc.cluster.local'
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: site
  namespace: {{ ns }}
spec:
  template:
    spec:
      containers:
        - image: {{ site_image }}
          name: site
          envFrom:
            - configMapRef: {name: site-config}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mysql
"""


def test_a_versioned_workload_is_its_application(ctx):
    from supagent.knowledge import projects as P

    found, names = P.facts(units({"platform/kube/book.yaml": BOOK}))
    assert {"details", "ratings", "mongodb"} <= set(names["parts"]) and "details-v1" not in names["parts"]
    assert names["aliases"]["details-v1"] == "details" and names["aliases"]["ratings-v2"] == "ratings"
    assert not any(o == "test" for _s, _v, o in triples(found))           # a database's name is no part


def test_a_templated_manifest_is_read(ctx):
    from supagent.knowledge import projects as P

    assert P.untemplated("a: {{ x }}\n{% if y %}\nb: '{{ z }}'\n{% endif %}\n") == "a: tpl\nb: 'tpl'\n"
    found, names = P.facts(units({"k8s/site.yml": TEMPLATED}))
    assert {"site", "mysql"} <= set(names["parts"])


def test_a_role_applying_manifests_is_no_part(ctx):
    from supagent.knowledge import projects as P

    assert P.Role("vendor.k8s_manifests", None).part is None
    assert P.Role("vendor.app-deploy", None).part is None


def test_a_compose_network_alias_is_another_name(ctx):
    from supagent.knowledge import projects as P

    compose = ("services:\n  chat:\n    image: chat\n    networks:\n      meet:\n        aliases:\n"
               "          - ${CHAT_HOST:-xmpp.meet.local}\n  web:\n    image: web\n")
    _f, names = P.facts(units({"docker-compose.yml": compose}))
    assert names["aliases"]["xmpp.meet.local"] == "chat" and names["aliases"]["xmpp"] == "chat"


def _code(path, text, owner, parts=()):
    from supagent.knowledge.understand import Names, discover, facts_of

    n = Names()
    for p in parts:
        n.add_part(p)
    u = {"ukey": path, "path": path, "kind": "file", "title": path, "text": text, "meta": {}}
    u["found"] = discover(u)
    return {(f["subject"], f["verb"], f["obj"]) for f in facts_of(u, owner, n, {})}


def test_an_address_variables_default_in_code_is_a_call(ctx):
    py = 'detailsHostname = "details" if (os.environ.get("DETAILS_HOSTNAME") is None) else os.environ.get("X")\n'
    js = "var catalogueHost = process.env.CATALOGUE_HOST || 'catalogue'\nvar redisHost = process.env.REDIS_HOST || 'redis'\n"
    java = 'String h = System.getenv("RATINGS_HOSTNAME") == null ? "ratings" : System.getenv("RATINGS_HOSTNAME");\n'
    assert _code("src/page/page.py", py, "page", ("page", "details")) == {("page", "calls", "details")}
    assert _code("cart/server.js", js, "cart", ("cart", "catalogue", "redis")) == \
        {("cart", "calls", "catalogue"), ("cart", "uses", "redis")}
    assert _code("src/reviews/Rest.java", java, "reviews", ("reviews", "ratings")) == {("reviews", "calls", "ratings")}


def test_public_sites_downloads_labels_and_pages_are_no_endpoints(ctx):
    text = ('privacy = "https://policies.example-cloud.com/privacy"\nterms_link: "https://www.tube.com/t/terms"\n'
            'LABEL org.opencontainers.image.url="https://vendor.org/app/"\nRUN curl -sSf https://get.tool.sh/x | sh\n'
            '<!DOCTYPE c PUBLIC "-//x//DTD" "http://www.crawl.com/dtds/configuration_1_2.dtd">\n'
            "gateway_url: 'https://pay.provider.com/api'\n")
    assert _code("conf/app.conf", text, "shop", ("shop",)) == {("shop", "calls", "provider")}


def test_routes_a_request_as_a_thing_and_other_languages(ctx):
    t = facts("The gateway routes the requests to the users service and the orders service; the catalog is reloaded "
              "on each request, introducing a delay in the frontend. Ratings are stored in MongoDB. Der Pod schreibt in "
              "die Datenbank db. Das Backend ruft die Datenbank db auf. Kibana lit ses données dans Elasticsearch.",
              parts=("gateway", "users service", "orders service", "catalog", "frontend", "Ratings", "MongoDB", "Pod",
                     "db", "Backend", "Kibana", "Elasticsearch"))
    assert {("gateway", "calls", "users service"), ("gateway", "calls", "orders service"),
            ("Ratings", "sends_to", "MongoDB"), ("Pod", "sends_to", "db"), ("Backend", "calls", "db"),
            ("Kibana", "reads_from", "Elasticsearch")} <= t
    assert not any(o == "frontend" for _s, _v, o in t)
