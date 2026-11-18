import copy
import re
import pymongo
from fastapi import HTTPException
from .enrich_messages import enrich_messages_with_referenced
from .Database import pad_id


def cursor_pagination(collection_messages, query: dict, prev_page_cursor=None, around_page_cursor=None, next_page_cursor=None, limit=100, guild_id=None):
    cursors = (prev_page_cursor, around_page_cursor, next_page_cursor)
    if sum(value is not None for value in cursors) > 1:
        raise HTTPException(status_code=400, detail="Only one pagination cursor can be provided")
    for value in cursors:
        if value is not None and re.fullmatch(r"[0-9]{1,24}", str(value)) is None:
            raise HTTPException(status_code=400, detail="Pagination cursors must be numeric IDs of at most 24 digits")
    if isinstance(limit, bool) or not re.fullmatch(r"[0-9]+", str(limit)):
        raise HTTPException(status_code=400, detail="limit is not an integer")
    limit = int(limit)
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    prev_page_cursor = pad_id(prev_page_cursor)
    around_page_cursor = pad_id(around_page_cursor)
    next_page_cursor = pad_id(next_page_cursor)
    if all(value is None for value in cursors):
        next_page_cursor = pad_id(0)

    # Never replace a search's existing _id predicate with a page boundary.
    # Both conditions must apply, and the caller's query must remain unchanged.
    base_query = copy.deepcopy(query)

    def bounded(condition):
        return {"$and": [base_query, {"_id": condition}]}

    def select(condition, direction, size):
        if size == 0:  # Mongo limit(0) means unlimited, not an empty page.
            return []
        return list(collection_messages.find(bounded(condition)).sort("_id", direction).limit(size))

    if prev_page_cursor is not None:
        messages = select({"$lt": prev_page_cursor}, pymongo.DESCENDING, limit)
        messages.reverse()
    elif next_page_cursor is not None:
        messages = select({"$gt": next_page_cursor}, pymongo.ASCENDING, limit)
    else:
        left = select({"$lte": around_page_cursor}, pymongo.DESCENDING, (limit + 1) // 2)
        left.reverse()
        right = select({"$gt": around_page_cursor}, pymongo.ASCENDING, limit // 2)
        messages = left + right

    anchor = prev_page_cursor or next_page_cursor or around_page_cursor
    first = messages[0]["_id"] if messages else anchor
    last = messages[-1]["_id"] if messages else anchor
    def exists(condition):
        return bool(list(collection_messages.find(bounded(condition), {"_id": 1}).limit(1)))
    prev_page = first if exists({"$lt": first}) else None
    next_page = last if exists({"$gt": last}) else None
    ids = [message["_id"] for message in messages]
    return {
        "prevPage": prev_page,
        "messageIds": ids,
        "nextPage": next_page,
        "messages": enrich_messages_with_referenced(messages, guild_id),
    }
