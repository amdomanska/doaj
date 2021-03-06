from portality.view import oaipmh
from portality.models import OAIPMHJournal, OAIPMHArticle
from doajtest.helpers import DoajTestCase
from doajtest.fixtures import JournalFixtureFactory
from portality import models
from portality.app import app
from lxml import etree
from datetime import datetime, timedelta
from freezegun import freeze_time

class TestClient(DoajTestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True

    def setUp(self):
        super(TestClient, self).setUp()

        # We're going to need this a lot.
        self.oai_ns = {'oai': 'http://www.openarchives.org/OAI/2.0/',
                       'oai_dc': 'http://www.openarchives.org/OAI/2.0/oai_dc/',
                       'dc': 'http://purl.org/dc/elements/1.1/'}

    def test_01_oai_ListMetadataFormats(self):
        """ Check we get the correct response from the OAI endpoint ListMetdataFormats request"""
        with app.test_client() as t_client:
            resp = t_client.get('/oai?verb=ListMetadataFormats')
            assert resp.status_code == 200

            t = etree.fromstring(resp.data)
            assert t.xpath('/oai:OAI-PMH/oai:ListMetadataFormats/oai:metadataFormat/oai:metadataPrefix', namespaces=self.oai_ns)[0].text == 'oai_dc'

    def test_02_oai_journals(self):
        """test if the OAI-PMH journal feed returns records and only displays journals accepted in DOAJ"""
        journal_sources = JournalFixtureFactory.make_many_journal_sources(2, in_doaj=True)
        j_public = models.Journal(**journal_sources[0])
        j_public.save(blocking=True)

        j_private = models.Journal(**journal_sources[1])
        j_private.set_in_doaj(False)
        j_private.save(blocking=True)

        with app.test_client() as t_client:
            resp = t_client.get('/oai?verb=ListRecords&metadataPrefix=oai_dc')
            assert resp.status_code == 200

            t = etree.fromstring(resp.data)
            records = t.xpath('/oai:OAI-PMH/oai:ListRecords', namespaces=self.oai_ns)

            # Check we only have one journal returned
            assert len(records[0].xpath('//oai:record', namespaces=self.oai_ns)) == 1

            # Check we have the correct journal
            assert records[0].xpath('//dc:title', namespaces=self.oai_ns)[0].text == j_public.bibjson().title

    def test_03_oai_resumption_token(self):
        """ Test the behaviour of the ResumptionToken in the OAI interface"""

        # Set the OAI interface to only return two identifiers at a time
        app.config['OAIPMH_LIST_IDENTIFIERS_PAGE_SIZE'] = 2

        [j0, j1, j2, j3, j4] = JournalFixtureFactory.make_many_journal_sources(5, in_doaj=True)

        # Save a single journal in the index
        jm0 = models.Journal(**j0)
        jm0.save(blocking=True)

        # ListIdentifiers - we expect no resumptionToken because all results are returned
        with app.test_client() as t_client:
            resp = t_client.get('/oai?verb=ListIdentifiers&metadataPrefix=oai_dc')
            t = etree.fromstring(resp.data)
            assert t.xpath('//oai:identifier', namespaces=self.oai_ns)[0].text == 'oai:doaj.org/journal:journalid0'
            assert t.xpath('//oai:resumptionToken', namespaces=self.oai_ns) == []

        # Populate index with 4 more journals
        for j in [j1, j2, j3, j4]:
            jm = models.Journal(**j)
            jm.save(blocking=True)

        # ListIdentifiers - we expect 5 total results and a resumptionToken to fetch the rest
        with app.test_client() as t_client:
            resp = t_client.get('/oai?verb=ListIdentifiers&metadataPrefix=oai_dc')
            t = etree.fromstring(resp.data)
            #print etree.tostring(t, pretty_print=True)
            rt = t.xpath('//oai:resumptionToken', namespaces=self.oai_ns)[0]
            assert rt.get('completeListSize') == '5'
            assert rt.get('cursor') == '2'

            # Get the next result
            resp2 = t_client.get('/oai?verb=ListIdentifiers&resumptionToken={0}'.format(rt.text))
            t = etree.fromstring(resp2.data)
            #print etree.tostring(t, pretty_print=True)
            rt2 = t.xpath('//oai:resumptionToken', namespaces=self.oai_ns)[0]
            assert rt2.get('completeListSize') == '5'
            assert rt2.get('cursor') == '4'

            # And the final result - check we get an empty resumptionToken
            resp3 = t_client.get('/oai?verb=ListIdentifiers&resumptionToken={0}'.format(rt2.text))
            t = etree.fromstring(resp3.data)
            #print etree.tostring(t, pretty_print=True)
            rt3 = t.xpath('//oai:resumptionToken', namespaces=self.oai_ns)[0]
            assert rt3.get('completeListSize') == '5'
            assert rt3.get('cursor') == '5'
            assert rt3.text is None

            # We should get an error if we request again with an empty resumptionToken
            resp4 = t_client.get('/oai?verb=ListIdentifiers&resumptionToken={0}'.format(rt3.text))
            assert resp4.status_code == 200                                   # fixme: should this be a real error code?
            t = etree.fromstring(resp4.data)
            #print etree.tostring(t, pretty_print=True)

            err = t.xpath('//oai:error', namespaces=self.oai_ns)[0]
            assert 'the resumptionToken argument is invalid or expired' in err.text

    def test_04_oai_changing_index(self):
        """ Check that changes to the index don't appear in in-progress requests """

        # Set the OAI interface to only return two identifiers at a time
        app.config['OAIPMH_LIST_IDENTIFIERS_PAGE_SIZE'] = 2

        journals = JournalFixtureFactory.make_many_journal_sources(4, in_doaj=True)

        # Save our journals to the index
        for j in journals[:3]:
            jm = models.Journal(**j)
            jm.save(blocking=True)

        # ListRecords - we expect 3 total results and a resumptionToken to fetch the rest
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
        with app.test_client() as t_client:
            resp = t_client.get('/oai?verb=ListRecords&metadataPrefix=oai_dc&from={0}'.format(yesterday))
            t = etree.fromstring(resp.data)
            #print etree.tostring(t, pretty_print=True)
            rt = t.xpath('//oai:resumptionToken', namespaces=self.oai_ns)[0]
            assert rt.get('completeListSize') == '3'
            assert rt.get('cursor') == '2'

            # Save another journal to the index
            [j] = journals[3:]
            jm = models.Journal(**j)
            jm.save(blocking=True)

            # Get the next result - the new journal shouldn't be added to the results
            resp2 = t_client.get('/oai?verb=ListRecords&resumptionToken={0}'.format(rt.text))
            t = etree.fromstring(resp2.data)
            #print etree.tostring(t, pretty_print=True)
            rt2 = t.xpath('//oai:resumptionToken', namespaces=self.oai_ns)[0]
            assert rt2.get('completeListSize') == '3'
            assert rt2.get('cursor') == '3'

            # Start a new request - we should see the new journal
            resp3 = t_client.get('/oai?verb=ListRecords&metadataPrefix=oai_dc&from={0}'.format(yesterday))
            t = etree.fromstring(resp3.data)
            #print etree.tostring(t, pretty_print=True)
            rt = t.xpath('//oai:resumptionToken', namespaces=self.oai_ns)[0]
            assert rt.get('completeListSize') == '4'

    def test_05_date_ranges(self):
        """ Check that the interface adheres to the dates that records were added """

        # Set the OAI interface to only return one identifier at a time
        app.config['OAIPMH_LIST_IDENTIFIERS_PAGE_SIZE'] = 1

        journals = JournalFixtureFactory.make_many_journal_sources(4, in_doaj=True)

        now = datetime.utcnow()
        yesterday = datetime.utcnow() - timedelta(days=1)
        day_before_yesterday = datetime.utcnow() - timedelta(days=2)
        two_days_before_yesterday = datetime.utcnow() - timedelta(days=3)

        # Save half of our journals 2 days ago
        with freeze_time(day_before_yesterday):
            for j in journals[:2]:
                jm = models.Journal(**j)
                jm.save(blocking=True)

        # Save the other half of our journals today
        with freeze_time(now):
            for j in journals[2:]:
                jm = models.Journal(**j)
                jm.save(blocking=True)

        # Request OAI journals since yesterday (looking for today's results only)
        with app.test_client() as t_client:
            resp = t_client.get('/oai?verb=ListRecords&metadataPrefix=oai_dc&from={0}'.format(yesterday.strftime('%Y-%m-%d')))
            t = etree.fromstring(resp.data)
            #print etree.tostring(t, pretty_print=True)
            rt = t.xpath('//oai:resumptionToken', namespaces=self.oai_ns)[0]
            assert rt.get('completeListSize') == '2'
            assert rt.get('cursor') == '1'

            for title in t.xpath('//dc:title', namespaces=self.oai_ns):
                assert title.text in [journals[2]['bibjson']['title'], journals[3]['bibjson']['title']]

        # Request OAI journals from 3 days ago to yesterday (expecting the 2 days ago results)
        with app.test_client() as t_client:
            resp = t_client.get('/oai?verb=ListRecords&metadataPrefix=oai_dc&from={0}&until={1}'.format(
                two_days_before_yesterday.strftime('%Y-%m-%d'), yesterday.strftime('%Y-%m-%d')))
            t = etree.fromstring(resp.data)
            #print etree.tostring(t, pretty_print=True)
            rt = t.xpath('//oai:resumptionToken', namespaces=self.oai_ns)[0]
            assert rt.get('completeListSize') == '2'
            assert rt.get('cursor') == '1'

            for title in t.xpath('//dc:title', namespaces=self.oai_ns):
                assert title.text in [journals[0]['bibjson']['title'], journals[1]['bibjson']['title']]
