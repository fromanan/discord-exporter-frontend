import asyncio
import copy
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import mongomock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Import the real routes with an isolated Mongo substitute, never the user's DB.
with patch("pymongo.MongoClient", mongomock.MongoClient):
    search = importlib.import_module("src.search.search")
    pagination = importlib.import_module("src.common.cursor_pagination")


def pid(value):
    return str(value).zfill(24)


class SearchPaginationTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().db
        self.messages = self.db["messages"]
        self.db.authors.insert_many([
            {"_id": pid(11), "names": ["Alice#0000"], "nicknames": ["First User", "Shared"]},
            {"_id": pid(22), "names": ["Bob#0000"], "nicknames": ["Second User", "Shared"]},
        ])
        self.db.channels.insert_many([
            {"_id": pid(101), "name": "general", "category": "A", "categoryId": pid(201)},
            {"_id": pid(102), "name": "other", "category": "B", "categoryId": pid(202)},
        ])
        self.messages.insert_many([
            {"_id": pid(i), "author": {"_id": pid(11 if i % 2 else 22)},
             "mentions": [{"_id": pid(22 if i % 2 else 11)}], "reactions": [],
             "channelId": pid(101 if i <= 90 else 102), "content": {"content": "hello world"},
             "timestamp": "2026-11-18T00:00:00", "embeds": [], "attachments": []}
            for i in range(1, 121)
        ])
        self.patches = [
            patch.object(search.Database, "get_guild_collection", side_effect=lambda guild, name: self.db[name]),
            patch.object(search.Database, "get_denylisted_user_ids", return_value=[]),
            patch.object(pagination, "enrich_messages_with_referenced", side_effect=lambda rows, guild: rows),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def run_search(self, prompt, **kwargs):
        return asyncio.run(search.search_messages_(pid(1), prompt, **kwargs))

    def test_unknown_author_is_empty_in_results_and_count(self):
        self.assertEqual([], self.run_search("from:nobody")["messageIds"])
        self.assertEqual(0, self.run_search("from:nobody", return_count=True))

    def test_http_search_requests_are_bounded_and_keep_user_filter_on_next_page(self):
        app = FastAPI()
        app.include_router(search.router)
        with TestClient(app) as client:
            params = {"guild_id": pid(1), "prompt": "from:<@11>", "limit": 7}
            first = client.get("/guild/search", params=params)
            self.assertEqual(200, first.status_code)
            self.assertEqual(7, len(first.json()["messages"]))
            second = client.get("/guild/search", params={**params, "next_page_cursor": first.json()["nextPage"]})
            self.assertEqual(200, second.status_code)
            self.assertEqual(7, len(second.json()["messages"]))
            self.assertEqual({pid(11)}, {row["author"]["_id"] for row in second.json()["messages"]})
            self.assertFalse(set(first.json()["messageIds"]) & set(second.json()["messageIds"]))
            self.assertEqual(400, client.get("/guild/search", params={**params, "limit": 501}).status_code)

    def test_http_unknown_and_ambiguous_users_never_return_other_users(self):
        app = FastAPI()
        app.include_router(search.router)
        with TestClient(app) as client:
            unknown = client.get("/guild/search", params={"guild_id": pid(1), "prompt": "from:nobody"})
            self.assertEqual(200, unknown.status_code)
            self.assertEqual([], unknown.json()["messageIds"])
            ambiguous = client.get("/guild/search", params={"guild_id": pid(1), "prompt": "from:Shared"})
            self.assertEqual(400, ambiguous.status_code)
            self.assertIn("select a user suggestion", ambiguous.json()["detail"])

    def test_author_names_mentions_and_ids_select_exact_account(self):
        for prompt in ("from:Alice", "FROM:@alice", 'from:"First User"', "from:11", "from:<@11>", "from:<@!11>", "from_id:11"):
            with self.subTest(prompt=prompt):
                result = self.run_search(prompt, limit=17)
                self.assertEqual(17, len(result["messages"]))
                self.assertEqual({pid(11)}, {row["author"]["_id"] for row in result["messages"]})
                self.assertEqual(60, self.run_search(prompt, return_count=True))

    def test_duplicate_names_require_identity_instead_of_matching_other_account(self):
        self.db.authors.insert_one({"_id": pid(33), "names": ["Alice#0000"], "nicknames": []})
        with self.assertRaises(HTTPException) as failure:
            self.run_search("from:Alice")
        self.assertEqual(400, failure.exception.status_code)
        self.assertIn("multiple captured accounts", failure.exception.detail)
        self.assertEqual({pid(11)}, {row["author"]["_id"] for row in self.run_search("from:<@11>")["messages"]})

    def test_ambiguous_nickname_is_not_silently_expanded(self):
        with self.assertRaises(HTTPException):
            self.run_search("from:Shared")

    def test_user_regex_characters_are_literal(self):
        self.assertEqual([], self.run_search("from:.*")["messageIds"])

    def test_denylisted_requested_user_cannot_widen_results(self):
        with patch.object(search.Database, "get_denylisted_user_ids", return_value=[pid(11)]):
            self.assertEqual([], self.run_search("from:<@11>")["messageIds"])
            self.assertEqual(0, self.run_search("from:Alice", return_count=True))
            self.assertEqual({pid(22)}, {row["author"]["_id"] for row in self.run_search("hello")["messages"]})

    def test_unknown_mentions_reactions_and_channels_remain_restrictive(self):
        for prompt in ("mentions:nobody", "reaction_from:nobody", "in:missing", "category:missing", "from:"):
            with self.subTest(prompt=prompt):
                self.assertEqual([], self.run_search(prompt)["messageIds"])

    def test_numeric_mentions_resolve_as_user_ids(self):
        self.assertEqual({pid(22)}, {row["author"]["_id"] for row in self.run_search("mentions:<@11>")["messages"]})

    def test_message_id_filter_is_paginated_and_preserved_across_pages(self):
        query = {"_id": {"$in": [pid(i) for i in range(1, 106)]}, "author._id": pid(11)}
        original = copy.deepcopy(query)
        cursor = pid(0)
        seen = []
        while cursor is not None:
            page = pagination.cursor_pagination(self.messages, query, next_page_cursor=cursor, limit=7)
            self.assertLessEqual(len(page["messageIds"]), 7)
            seen.extend(page["messageIds"])
            cursor = page["nextPage"]
        self.assertEqual([pid(i) for i in range(1, 106, 2)], seen)
        self.assertEqual(original, query)

    def test_search_message_id_operator_cannot_bypass_limit(self):
        prompt = " ".join("message_id:" + str(i) for i in range(1, 81))
        page = self.run_search(prompt, limit=3)
        self.assertEqual([pid(1), pid(2), pid(3)], page["messageIds"])
        self.assertIsNotNone(page["nextPage"])

    def test_reverse_and_around_pages_preserve_filters_and_odd_limits(self):
        query = {"author._id": pid(11), "_id": {"$in": [pid(i) for i in range(1, 81)]}}
        before = pagination.cursor_pagination(self.messages, query, prev_page_cursor=pid(51), limit=3)
        self.assertEqual([pid(45), pid(47), pid(49)], before["messageIds"])
        for size in (1, 3, 5):
            page = pagination.cursor_pagination(self.messages, query, around_page_cursor=pid(51), limit=size)
            self.assertEqual(size, len(page["messageIds"]))
            self.assertIn(pid(51), page["messageIds"])
            self.assertEqual({pid(11)}, {row["author"]["_id"] for row in page["messages"]})

    def test_empty_filtered_page_has_no_unfiltered_navigation(self):
        page = pagination.cursor_pagination(self.messages, {"author._id": pid(999)}, next_page_cursor=pid(0), limit=2)
        self.assertEqual([], page["messageIds"])
        self.assertIsNone(page["prevPage"])
        self.assertIsNone(page["nextPage"])

    def test_invalid_limits_and_cursors_are_rejected_before_database_reads(self):
        for value in (0, -1, 501, 1.5, True, "bad"):
            with self.subTest(limit=value), self.assertRaises(HTTPException):
                pagination.cursor_pagination(self.messages, {}, limit=value)
        for value in ("", "bad", "1" * 25, "١"):
            with self.subTest(cursor=value), self.assertRaises(HTTPException):
                pagination.cursor_pagination(self.messages, {}, next_page_cursor=value)
        with self.assertRaises(HTTPException):
            pagination.cursor_pagination(self.messages, {}, prev_page_cursor="1", next_page_cursor="2")

    def test_every_page_and_probe_has_a_positive_database_limit(self):
        actual_find = self.messages.find
        limits = []

        class GuardedCursor:
            def __init__(self, cursor): self.cursor, self.size = cursor, None
            def sort(self, *args): self.cursor = self.cursor.sort(*args); return self
            def limit(self, size): self.size = size; limits.append(size); self.cursor = self.cursor.limit(size); return self
            def __iter__(self):
                if self.size is None or self.size <= 0: raise AssertionError("Unbounded database read")
                return iter(self.cursor)

        with patch.object(self.messages, "find", side_effect=lambda *args, **kwargs: GuardedCursor(actual_find(*args, **kwargs))):
            pagination.cursor_pagination(self.messages, {"_id": {"$in": [pid(1), pid(2)]}}, around_page_cursor=pid(1), limit=1)
        self.assertTrue(limits)
        self.assertTrue(all(0 < size <= 1 for size in limits))


if __name__ == "__main__":
    unittest.main()
