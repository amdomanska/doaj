from parameterized import parameterized
from combinatrix.testintegration import load_parameter_sets

from doajtest.fixtures import ArticleFixtureFactory, JournalFixtureFactory, AccountFixtureFactory
from doajtest.helpers import DoajTestCase
from portality.bll import DOAJ
from portality.bll import exceptions
from portality.models import Article, Journal, Account
from portality.lib.paths import rel2abs
from doajtest.mocks.bll_article import BLLArticleMockFactory
from datetime import datetime

def load_cases():
    return load_parameter_sets(rel2abs(__file__, "..", "matrices", "article_get_duplicates"), "get_duplicates", "test_id", {"test_id" : []})


EXCEPTIONS = {
    "ArgumentException" : exceptions.ArgumentException
}

class TestBLLArticleGetDuplicates(DoajTestCase):

    def setUp(self):
        super(TestBLLArticleGetDuplicates, self).setUp()
        self.svc = DOAJ.articleService()
        self._old_discover_duplicates = self.svc.discover_duplicates

    def tearDown(self):
        self.svc.discover_duplicates = self._old_discover_duplicates
        super(TestBLLArticleGetDuplicates, self).tearDown()

    @parameterized.expand(load_cases)
    def test_01_get_duplicates(self, name, kwargs):

        article_arg = kwargs.get("article")
        owner_arg = kwargs.get("owner")
        doi_duplicates_arg = kwargs.get("doi_duplicates")
        fulltext_duplicates_arg = kwargs.get("fulltext_duplicates")
        overlap_arg = kwargs.get("overlap")
        raises_arg = kwargs.get("raises")

        raises = EXCEPTIONS.get(raises_arg)

        doi_duplicates = -1
        if doi_duplicates_arg not in ["-"]:
            doi_duplicates = int(doi_duplicates_arg)

        fulltext_duplicates = -1
        if fulltext_duplicates_arg not in ["-"]:
            fulltext_duplicates = int(fulltext_duplicates_arg)

        overlap = -1
        if overlap_arg not in ["-"]:
            overlap = int(overlap_arg)

        expected_count = doi_duplicates + fulltext_duplicates - overlap

        ###############################################
        ## set up

        owner = None
        if owner_arg != "no":
            owner = Account(**AccountFixtureFactory.make_publisher_source())

        owner_id = None
        if owner is not None:
            owner_id = owner.id

        # generate our incoming article
        article = None
        if article_arg == "yes":
            source = ArticleFixtureFactory.make_article_source()
            article = Article(**source)
            article.set_id()

        mock = BLLArticleMockFactory.discover_duplicates(doi_duplicates, fulltext_duplicates, overlap)
        self.svc.discover_duplicates = mock

        ###########################################################
        # Execution

        first_article = None

        # first do get_duplicates
        if raises is not None:
            with self.assertRaises(raises):
                self.svc.get_duplicates(article, owner_id)
        else:
            duplicates = self.svc.get_duplicates(article, owner_id)

            if len(duplicates) > 0:
                first_article = duplicates[0]

            # check that we have the number of results we expected
            assert len(duplicates) == expected_count

            # check that the articles are unique in the list
            article_ids = [a.id for a in duplicates]
            article_ids.sort()
            deduped = list(set(article_ids))
            deduped.sort()  # so it's comparable to the article_ids list, as the set() call destroys ordering
            assert article_ids == deduped   # i.e. that there were no duplicates

            # check that the articles are ordered by last_updated
            last_updateds = [datetime.strptime(a.last_updated, "%Y-%m-%dT%H:%M:%SZ") for a in duplicates]
            sorted_lu = sorted(last_updateds, reverse=True)
            assert sorted_lu == last_updateds   # i.e. they were already sorted

        # then the same again on the singular get_duplicate
        if raises is not None:
            with self.assertRaises(raises):
                self.svc.get_duplicate(article, owner_id)
        else:
            duplicate = self.svc.get_duplicate(article, owner_id)

            if expected_count > 0:
                assert isinstance(duplicate, Article)
                assert duplicate.id == first_article.id
            else:
                assert duplicate is None

    def test_02_get_duplicates_tricked(self):
        account = Account()
        account.add_role("publisher")
        account.set_id("test")
        account.save(blocking=True)

        j = Journal()
        jbj = j.bibjson()
        jbj.add_identifier(jbj.E_ISSN, "1111-1111")
        jbj.title = "Journal"
        j.set_owner("test")
        j.save(blocking=True)

        a1 = Article()
        bj1 = a1.bibjson()
        bj1.add_identifier(bj1.E_ISSN, "1111-1111")
        bj1.add_identifier(bj1.DOI, "10.1234/1111")
        bj1.add_url("http://10.1234/1111", bj1.FULLTEXT)
        bj1.title = "One"
        a1.save(blocking=True)

        a2 = Article()
        bj2 = a2.bibjson()
        bj2.add_identifier(bj2.E_ISSN, "1111-1111")
        bj2.add_identifier(bj2.DOI, "10.1234/2222")
        bj2.add_url("http://10.1234/2222", bj2.FULLTEXT)
        bj2.title = "Two"
        a2.save(blocking=True)

        # this contains a mix of both ids
        a3 = Article()
        bj3 = a3.bibjson()
        bj3.add_identifier(bj3.E_ISSN, "1111-1111")
        bj3.add_identifier(bj3.DOI, "10.1234/1111")
        bj3.add_url("http://10.1234/2222", bj3.FULLTEXT)
        bj3.title = "Three"

        # first check that what we see is two possible duplicates
        dups = self.svc.get_duplicates(a3)
        assert len(dups) == 2

        # now do the update, which should overwrite one of the articles
        # (we don't know which one)
        self.svc.create_article(a3, account)

        import time
        time.sleep(2)

        # check that either way round we look at it, we now have a duplicate
        # in the system
        dups = self.svc.get_duplicates(a1)
        assert len(dups) == 1

        dups = self.svc.get_duplicates(a2)
        assert len(dups) == 1
