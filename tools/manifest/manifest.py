import itertools
import json
import os

from collections import defaultdict
from fnmatch import fnmatchcase

from six import iteritems, iterkeys, itervalues, string_types
from six.moves import urllib

from . import vcs
from .item import (ManualTest, WebDriverSpecTest, Stub, RefTestNode, RefTest,
                   TestharnessTest, SupportFile, ConformanceCheckerTest, VisualTest)
from .log import get_logger
from .typedata import TypeData as New_TypeData
from .utils import from_os_path, to_os_path

MYPY = False
if MYPY:
    # MYPY is set to True when run under Mypy.
    from typing import Dict
    from types import ModuleType

try:
    import ujson
    fast_json = ujson  # type: ModuleType
except ImportError:
    fast_json = json

CURRENT_VERSION = 7


class ManifestError(Exception):
    pass


class ManifestVersionMismatch(ManifestError):
    pass


item_classes = {"testharness": TestharnessTest,
                "reftest": RefTest,
                "reftest_node": RefTestNode,
                "manual": ManualTest,
                "stub": Stub,
                "wdspec": WebDriverSpecTest,
                "conformancechecker": ConformanceCheckerTest,
                "visual": VisualTest,
                "support": SupportFile}


class SkipNode(dict):
    __slots__ = ("skip",)

    def __init__(self, skip=False):
        self.skip = skip

    @classmethod
    def build(cls, include=None, exclude=None):
        if include is None:
            include = []
        if exclude is None:
            exclude = []

        items = [(x, False) for x in include] if include else []
        if exclude:
            items.extend((x, True) for x in exclude)

        skip_trie = cls()

        # we need to build in increasing depth
        for path, skip in sorted(items, key=lambda x: x[0].count("/")):
            if path == "":
                skip_trie.skip = skip
                continue

            components = path.split("/")
            node = skip_trie
            for component in components:
                node = node.setdefault(component, cls(node.skip))
            node.skip = skip

        return skip_trie

    def is_skipped_path(self, path):
        if len(self) == 0:
            return self.skip

        path_components = path.split("/")

        node = self

        for component in path_components[:-1]:
            if component in node:
                node = node[component]
            else:
                return node.skip

        skipped = node.skip

        basename = path_components[-1]
        if basename in node:
            return node[basename].skip

        for child_path, child_node in iteritems(node):
            if fnmatchcase(basename, child_path):
                return child_node.skip

        return skipped

    def is_entirely_skipped_path(self, path):
        node = self

        if path != "":
            path_components = path.split("/")

            for component in path_components:
                if component in node:
                    node = node[component]
                else:
                    return node.skip

        skipped = node.skip
        if not skipped:
            return False

        # we now need to check all children are skip=True
        to_check = list(itervalues(node))
        while to_check:
            node = to_check.pop()
            if not node.skip:
                return False
            to_check.extend(itervalues(node))

        return True

    def is_skipped_item(self, item):
        if len(self) == 0:
            return self.skip

        try:
            url = item.url
        except AttributeError:
            return False

        assert url[0] == "/"

        url = urllib.parse.urlsplit(url)

        path_components = url.path[1:].split("/")

        node = self

        for component in path_components[:-1]:
            if component in node:
                node = node[component]
            else:
                return node.skip

        skipped = node.skip

        basenames = [path_components[-1]]
        if url.query:
            basenames.append("?".join([basename[-1], url.query]))
        if url.fragment:
            basenames.append("#".join([basenames[-1], url.fragment]))

        for basename in basenames:
            if basename in node:
                return node[basename].skip

            for child_path, child_node in iteritems(node):
                if fnmatchcase(basename, child_path):
                    return child_node.skip

        return skipped


class TypeData(object):
    def __init__(self, manifest, type_cls):
        """Dict-like object containing the TestItems for each test type.

        Loading an actual Item class for each test is unnecessarily
        slow, so this class allows lazy-loading of the test
        items. When the manifest is loaded we store the raw json
        corresponding to the test type, and only create an Item
        subclass when the test is accessed. In order to remain
        API-compatible with consumers that depend on getting an Item
        from iteration, we do egerly load all items when iterating
        over the class."""
        self.new_data = New_TypeData(manifest, type_cls)

    def __getitem__(self, key):
        k = from_os_path(key).split(u"/")
        return self.new_data[k]

    def __nonzero__(self):
        return bool(self.new_data)

    def __len__(self):
        return len(self.new_data)

    def __delitem__(self, key):
        k = from_os_path(key).split(u"/")
        del self.new_data[k]

    def __setitem__(self, key, value):
        k = from_os_path(key).split(u"/")
        self.new_data[k] = value

    def __contains__(self, key):
        k = from_os_path(key).split(u"/")
        return k in self.new_data

    def __iter__(self):
        for k in self.new_data:
            yield to_os_path(u"/".join(k))

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def clear(self):
        self.new_data.clear()

    def itervalues(self):
        return self.new_data.values()

    def iteritems(self):
        for k, v in self.new_data.items():
            yield (to_os_path(u"/".join(k)), v)

    def values(self):
        return self.itervalues()

    def items(self):
        return self.iteritems()

    def load(self, key):
        """Load a specific Item given a path"""
        pass

    def load_all(self):
        """Load all test items in this class"""
        pass

    def set_json(self, tests_root, data):
        self.new_data._json_data = data

    def to_json(self):
        return self.new_data.to_json()

    def paths(self):
        """Get a list of all paths containing items of this type,
        without actually constructing all the items"""
        rv = set()
        for k in self.new_data:
            rv.add(to_os_path(u"/".join(k)))
        return rv


class ManifestData(dict):
    def __init__(self, manifest):
        """Dictionary subclass containing a TypeData instance for each test type,
        keyed by type name"""
        self.initialized = False
        for key, value in iteritems(item_classes):
            self[key] = TypeData(manifest, value)
        self.initialized = True
        self.json_obj = None

    def __setitem__(self, key, value):
        if self.initialized:
            raise AttributeError
        dict.__setitem__(self, key, value)

    def paths(self):
        """Get a list of all paths containing test items
        without actually constructing all the items"""
        rv = set()
        for item_data in itervalues(self):
            rv |= set(item_data.paths())
        return rv


class Manifest(object):
    def __init__(self, tests_root=None, url_base="/"):
        assert url_base is not None
        self._path_hash = {}
        self._data = ManifestData(self)
        self._reftest_nodes_by_url = None
        self.tests_root = tests_root
        self.url_base = url_base

    def __iter__(self):
        return self.itertypes()

    def itertypes(self, *types):
        if not types:
            types = sorted(self._data.keys())
        for item_type in types:
            for path in sorted(self._data[item_type]):
                tests = self._data[item_type][path]
                yield item_type, path, tests

    def iterpath(self, path):
        for type_tests in self._data.values():
            for test in type_tests.get(path, set()):
                yield test

    def iterdir(self, dir_name):
        if not dir_name.endswith(os.path.sep):
            dir_name = dir_name + os.path.sep
        for type_tests in self._data.values():
            for path, tests in type_tests.iteritems():
                if path.startswith(dir_name):
                    for test in tests:
                        yield test

    @property
    def reftest_nodes_by_url(self):
        if self._reftest_nodes_by_url is None:
            by_url = {}
            for path, nodes in itertools.chain(iteritems(self._data.get("reftest", {})),
                                               iteritems(self._data.get("reftest_node", {}))):
                for node in nodes:
                    by_url[node.url] = node
            self._reftest_nodes_by_url = by_url
        return self._reftest_nodes_by_url

    def get_reference(self, url):
        return self.reftest_nodes_by_url.get(url)

    def update(self, tree):
        """Update the manifest given an iterable of items that make up the updated manifest.

        The iterable must either generate tuples of the form (SourceFile, True) for paths
        that are to be updated, or (path, False) for items that are not to be updated. This
        unusual API is designed as an optimistaion meaning that SourceFile items need not be
        constructed in the case we are not updating a path, but the absence of an item from
        the iterator may be used to remove defunct entries from the manifest."""
        reftest_nodes = []
        seen_files = set()

        changed = False
        reftest_changes = False

        # Create local variable references to these dicts so we avoid the
        # attribute access in the hot loop below
        path_hash = self._path_hash
        data = self._data

        prev_files = data.paths()

        reftest_types = ("reftest", "reftest_node")

        for source_file, update in tree:
            if not update:
                rel_path = source_file
                seen_files.add(rel_path)
                assert rel_path in path_hash
                old_hash, old_type = path_hash[rel_path]
                if old_type in reftest_types:
                    manifest_items = data[old_type][rel_path]
                    reftest_nodes.extend((item, old_hash) for item in manifest_items)
            else:
                rel_path = source_file.rel_path
                seen_files.add(rel_path)

                file_hash = source_file.hash

                is_new = rel_path not in path_hash
                hash_changed = False

                if not is_new:
                    old_hash, old_type = path_hash[rel_path]
                    if old_hash != file_hash:
                        new_type, manifest_items = source_file.manifest_items()
                        hash_changed = True
                        if new_type != old_type:
                            del data[old_type][rel_path]
                            if old_type in reftest_types:
                                reftest_changes = True
                    else:
                        new_type = old_type
                        if old_type in reftest_types:
                            manifest_items = data[old_type][rel_path]
                else:
                    new_type, manifest_items = source_file.manifest_items()

                if new_type in reftest_types:
                    reftest_nodes.extend((item, file_hash) for item in manifest_items)
                    if is_new or hash_changed:
                        reftest_changes = True
                elif is_new or hash_changed:
                    data[new_type][rel_path] = set(manifest_items)

                if is_new or hash_changed:
                    path_hash[rel_path] = (file_hash, new_type)
                    changed = True

        deleted = prev_files - seen_files
        if deleted:
            changed = True
            for rel_path in deleted:
                if rel_path in path_hash:
                    _, old_type = path_hash[rel_path]
                    if old_type in reftest_types:
                        reftest_changes = True
                    del path_hash[rel_path]
                    try:
                        del data[old_type][rel_path]
                    except KeyError:
                        pass
                else:
                    for test_data in itervalues(data):
                        if rel_path in test_data:
                            del test_data[rel_path]

        if reftest_changes:
            reftests, reftest_nodes, changed_hashes = self._compute_reftests(reftest_nodes)
            reftest_data = data["reftest"]
            reftest_data.clear()
            for path, items in iteritems(reftests):
                reftest_data[path] = items

            reftest_node_data = data["reftest_node"]
            reftest_node_data.clear()
            for path, items in iteritems(reftest_nodes):
                reftest_node_data[path] = items

            path_hash.update(changed_hashes)

        return changed

    def _compute_reftests(self, reftest_nodes):
        self._reftest_nodes_by_url = {}
        has_inbound = set()
        for item, _ in reftest_nodes:
            for ref_url, ref_type in item.references:
                has_inbound.add(ref_url)

        reftests = defaultdict(set)
        references = defaultdict(set)
        changed_hashes = {}

        for item, file_hash in reftest_nodes:
            if item.url in has_inbound:
                # This is a reference
                if isinstance(item, RefTest):
                    item = item.to_RefTestNode()
                    changed_hashes[item.path] = (file_hash,
                                                 item.item_type)
                references[item.path].add(item)
            else:
                if isinstance(item, RefTestNode):
                    item = item.to_RefTest()
                    changed_hashes[item.path] = (file_hash,
                                                 item.item_type)
                reftests[item.path].add(item)
            self._reftest_nodes_by_url[item.url] = item

        return reftests, references, changed_hashes

    def to_json(self):
        out_items = {
            test_type: type_paths.to_json()
            for test_type, type_paths in iteritems(self._data) if type_paths
        }
        rv = {"url_base": self.url_base,
              "paths": {from_os_path(k): v for k, v in iteritems(self._path_hash)},
              "items": out_items,
              "version": CURRENT_VERSION}
        return rv

    @classmethod
    def from_json(cls, tests_root, obj, types=None):
        version = obj.get("version")
        if version != CURRENT_VERSION:
            raise ManifestVersionMismatch

        self = cls(tests_root, url_base=obj.get("url_base", "/"))
        if not hasattr(obj, "items") and hasattr(obj, "paths"):
            raise ManifestError

        self._path_hash = {to_os_path(k): v for k, v in iteritems(obj["paths"])}

        for test_type, type_paths in iteritems(obj["items"]):
            if test_type not in item_classes:
                raise ManifestError

            if types and test_type not in types:
                continue

            self._data[test_type].set_json(tests_root, type_paths)

        return self


def load(tests_root, manifest, types=None):
    logger = get_logger()

    logger.warning("Prefer load_and_update instead")
    return _load(logger, tests_root, manifest, types)


__load_cache = {}  # type: Dict[str, Manifest]


def _load(logger, tests_root, manifest, types=None, allow_cached=True):
    # "manifest" is a path or file-like object.
    manifest_path = (manifest if isinstance(manifest, string_types)
                     else manifest.name)
    if allow_cached and manifest_path in __load_cache:
        return __load_cache[manifest_path]

    if isinstance(manifest, string_types):
        if os.path.exists(manifest):
            logger.debug("Opening manifest at %s" % manifest)
        else:
            logger.debug("Creating new manifest at %s" % manifest)
        try:
            with open(manifest) as f:
                rv = Manifest.from_json(tests_root,
                                        fast_json.load(f),
                                        types=types)
        except IOError:
            return None
        except ValueError:
            logger.warning("%r may be corrupted", manifest)
            return None
    else:
        rv = Manifest.from_json(tests_root,
                                fast_json.load(manifest),
                                types=types)

    if allow_cached:
        __load_cache[manifest_path] = rv
    return rv


def load_and_update(tests_root,
                    manifest_path,
                    url_base,
                    update=True,
                    rebuild=False,
                    metadata_path=None,
                    cache_root=None,
                    working_copy=True,
                    types=None,
                    write_manifest=True,
                    allow_cached=True):
    logger = get_logger()

    manifest = None
    if not rebuild:
        try:
            manifest = _load(logger,
                             tests_root,
                             manifest_path,
                             types=types,
                             allow_cached=allow_cached)
        except ManifestVersionMismatch:
            logger.info("Manifest version changed, rebuilding")

        if manifest is not None and manifest.url_base != url_base:
            logger.info("Manifest url base did not match, rebuilding")

    if manifest is None:
        manifest = Manifest(tests_root, url_base)
        update = True

    if update:
        tree = vcs.get_tree(tests_root, manifest, manifest_path, cache_root,
                            working_copy, rebuild)
        changed = manifest.update(tree)
        if write_manifest and changed:
            write(manifest, manifest_path)
        tree.dump_caches()

    return manifest


def write(manifest, manifest_path):
    dir_name = os.path.dirname(manifest_path)
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
    with open(manifest_path, "wb") as f:
        # Use ',' instead of the default ', ' separator to prevent trailing
        # spaces: https://docs.python.org/2/library/json.html#json.dump
        json.dump(manifest.to_json(), f,
                  sort_keys=True, indent=1, separators=(',', ': '))
        f.write("\n")
