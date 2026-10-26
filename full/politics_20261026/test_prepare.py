import json, pathlib, unittest
from prepare import OUT, ROOT, sha

class PreparedContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import prepare
        prepare.run()
    def test_history_retained_and_field_ids_do_not_collide(self):
        expected={'president':(94151,'12.01'),'senate':(3945,'12.02'),'house':(33805,'12.03')}
        for office,(n,fid) in expected.items():
            rows=[json.loads(x) for x in (OUT/f'{office}_candidates.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),n)
            self.assertTrue(all(r['field_id']==fid for r in rows))
    def test_repeated_totalvotes_are_per_row_provenance(self):
        rows=[json.loads(x) for x in (OUT/'president_candidates.jsonl').read_text().splitlines()[:20]]
        same=[r for r in rows if r['source_total_votes'] is not None]
        self.assertGreater(len(same),1)
        self.assertTrue(all(r['totalvotes_raw'] is not None for r in same))
        # Preparation creates source rows only; it never creates an aggregate total.
        self.assertTrue(all('reported_total_votes' not in r for r in same))
    def test_source_modes_and_totalvotes_remain_separate(self):
        rows=[json.loads(x) for x in (OUT/'president_candidates.jsonl').read_text().splitlines()]
        contests={}
        for r in rows:
            key=(r['geo_id'],r['source_row'].get('year'),r['stage'],r['is_special'],r['is_runoff'],r['source_version'])
            contests.setdefault(key,set()).add(r['result_mode'])
        self.assertTrue(any(len(modes)>1 for modes in contests.values()))
        raw_totals={}
        for row in rows:
            src=row['source_row']; key=(src.get('year'),src.get('state_fips') or src.get('state_po'),src.get('county_fips') or src.get('district') or src.get('state_po'),(src.get('stage') or 'GEN').upper(),str(src.get('special','False')).lower(),str(src.get('runoff','False')).lower(),(src.get('mode') or 'TOTAL').upper(),src.get('version'))
            raw_totals.setdefault(tuple(key),set()).add((row['totalvotes_raw'] or '').strip())
        reviews=[json.loads(x) for x in (OUT/'president_contest_review.jsonl').read_text().splitlines()]
        for review in reviews:
            values=raw_totals[tuple(review['contest_source_key'])]
            self.assertEqual(review['reported_total_votes_raw'],next(iter(values)) if len(values)==1 else None)
    def test_aian_period_and_quality_are_explicit(self):
        rows=[json.loads(x) for x in (OUT/'aian_county.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows),3222)
        self.assertTrue(all(r['field_id']=='01.04' and r['period_kind']=='multi_year' and r['period_month'] is None for r in rows))
        self.assertTrue(any(r['quality_status']=='nonmapping_geography' for r in rows))
        self.assertEqual(sum(r['quality_status']=='nonmapping_geography' for r in rows),11)
        self.assertTrue(all(r['raw_estimate_moe'] is not None and r['raw_denominator_moe'] is not None for r in rows))
    def test_contest_review_quarantines_ambiguous_rows(self):
        for office in ('president','house','senate'):
            records=[json.loads(x) for x in (OUT/f'{office}_contest_review.jsonl').read_text().splitlines()]
            self.assertTrue(records)
            self.assertTrue(all(r['result_mode'] for r in records))
        for office in ('president','senate'):
            records=[json.loads(x) for x in (OUT/f'{office}_contest_review.jsonl').read_text().splitlines()]
            self.assertTrue(any(r['party_aggregation_status']=='quarantined' for r in records))
    def test_senate_no_election_is_not_missing_or_zero(self):
        rows=[json.loads(x) for x in (OUT/'senate_2024_availability.jsonl').read_text().splitlines()]
        self.assertEqual(sum(r['quality_status']=='no_election' for r in rows),17)
        self.assertEqual(sum(r['quality_status']=='missing' for r in rows),0)
        self.assertTrue(all(r['geo_type']=='state' and r['field_id']=='12.02' for r in rows))
    def test_2024_house_at_large_id_uses_census_00(self):
        rows=[json.loads(x) for x in (OUT/'house_candidates.jsonl').read_text().splitlines()]
        ak=next(r for r in rows if r['source_row'].get('year')=='2024' and r['state_fips']=='02')
        self.assertEqual((ak['geo_id'],ak['district_code'],ak['boundary_vintage'],ak['congress_session']),('0200','00',2024,'119'))
        self.assertTrue(ak['is_at_large'])
    def test_geometry_vintage_and_at_large_codes(self):
        data=json.loads((OUT/'cd119_geometry_manifest.json').read_text())
        self.assertEqual(data['feature_count'],441)
        self.assertTrue(all(f['boundary_vintage']==2024 and f['congress_session']=='119' for f in data['features']))
        self.assertTrue(any(f['district_code']=='00' and f['is_at_large'] for f in data['features']))
        self.assertFalse(any(f['district_code']=='98' and f['is_at_large'] for f in data['features']))

if __name__=='__main__': unittest.main()
