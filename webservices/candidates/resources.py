from datetime import datetime
import re
import string

from flask.ext.restful import reqparse

from webservices.common.util import default_year, natural_number
from webservices.resources import SingleResource
from webservices import decoders
from .models import Candidate


def cleantext(text):
    if type(text) is str:
        text = re.sub(' +', ' ', text)
        text = re.sub('\\r|\\n', '', text)
        text = text.strip()
        return text
    else:
        return text


class BaseCandidateResource(Candidate):
    """Common Base Class for Candidate Resources. Not a Mixin as the resources
    also inherit from a model"""

    # @todo split this into smaller functions
    def format(self, data_dict, page_data, year):
        args = self.parser.parse_args()
        fields = self.find_fields(args)
        data = data_dict    # match naming in migrated code
        default_year = year

        results = []

        for cand in data:
            # aggregating data for each election across the tables
            elections = {}
            cand_data = {}

            for api_name, fec_name in self.dimcand_mapping:
                if fec_name in cand['dimcand']:
                    cand_data[api_name] = cand['dimcand'][fec_name]

            # Committee information
            if 'affiliated_committees' in cand:
                for cmte in cand['affiliated_committees']:
                    year = str(cmte['cand_election_yr'])
                    if len(cmte) > 0 and year not in elections:
                        elections[year] = {}

                    committee = {}
                    # not looking at the fields used for name matching
                    for api_name, fec_name in \
                            self.cand_committee_format_mapping:
                        if fec_name in cmte:
                            committee[api_name] = cmte[fec_name]

                    if cmte['dimcmte'][0]['dimcmteproperties'][0]:
                        # this should be most recent name
                        committee['committee_name'] = cmte['dimcmte'][0][
                            'dimcmteproperties'][-1]['cmte_nm']

                    if cmte['cmte_dsgn']:
                        committee['designation_full'] = \
                            decoders.designation[cmte['cmte_dsgn']]
                    if cmte['cmte_tp']:
                        committee['type_full'] = decoders.cmte[cmte['cmte_tp']]

                    if cmte['cmte_dsgn'] == 'P':
                        elections[year]['primary_committee'] = committee
                    elif 'affiliated_committees' not in elections[year]:
                        elections[year]['affiliated_committees'] = [committee]
                    else:
                        elections[year]['affiliated_committees'].append(
                            committee)

            for office in cand['dimcandoffice']:
                year = str(office['cand_election_yr'])
                if len(office) > 0 and year not in elections:
                    elections[year] = {}

                if fields == [] or 'election_year' in fields or '*' in fields:
                    elections[year]['election_year'] = int(year)

                # Office information
                for api_name, fec_name in self.office_mapping:
                    if fec_name in office['dimoffice']:
                        elections[year][api_name] = \
                            office['dimoffice'][fec_name]
                # Party information
                for api_name, fec_name in self.party_mapping:
                    if fec_name in office['dimparty']:
                        elections[year][api_name] = \
                            office['dimparty'][fec_name]

            # status information
            for status in cand['dimcandstatusici']:
                if status != {}:
                    year = str(status['election_yr'])
                    if year not in elections:
                        year = str(status['election_yr'])
                        elections[year] = {}

                    for api_name, fec_name in self.status_mapping:
                        if fec_name in status:
                            elections[year][api_name] = status[fec_name]

                    if status.get('cand_status') is not None:
                        elections[year]['candidate_status_full'] = \
                            decoders.status[status['cand_status']]

                    if status.get('ici_code') is not None:
                        elections[year]['incumbent_challenge_full'] = \
                            decoders.ici[status['ici_code']]

            # Using most recent name as full name
            if 'cand_nm' in cand['dimcandproperties'][0]:
                name = cand['dimcandproperties'][0]['cand_nm']
                cand_data['name'] = {}
                cand_data['name']['full_name'] = \
                    cand['dimcandproperties'][-1]['cand_nm']

                # let's do this for now, we could look for improvements in the
                # future
                if (len(name.split(',')) == 2
                        and len(name.split(',')[0].strip()) > 0
                        and len(name.split(',')[1].strip()) > 0):
                    cand_data['name']['name_1'] = name.split(',')[1].strip()
                    cand_data['name']['name_2'] = name.split(',')[0].strip()

            # properties has names and addresses
            addresses = []
            other_names = []
            for prop in cand['dimcandproperties']:
                if 'election_yr' in prop and year not in elections:
                    elections[year] = {}

                # Addresses
                one_address = {}
                for api_name, fec_name in self.property_fields_mapping:
                    if (fec_name in prop
                            and fec_name != "cand_nm"
                            and fec_name != "expire_date"):
                        one_address[api_name] = cleantext(prop[fec_name])
                    if prop.get('expire_date') is not None:
                        one_address['expire_date'] = datetime.strftime(
                            prop['expire_date'], '%Y-%m-%d')
                if one_address not in addresses and one_address != {}:
                    addresses.append(one_address)

                # Names (picking up name variations)
                if ('cand_nm' in prop
                        and ('other_names' in fields or '*' in fields)
                        and cand_data['name']['full_name'] != prop['cand_nm']
                        and prop['cand_nm'] not in other_names):
                    name = cleantext(prop['cand_nm'])
                    other_names.append(name)

            if len(addresses) > 0:
                cand_data['mailing_addresses'] = addresses
            if len(other_names) > 0:
                cand_data['name']['other_names'] = other_names

            # Order election data so the most recent is first and just show
            # years requested

            years = []
            default_years = default_year.split(',')
            for year in elections:
                if year in default_years or default_year == '*':
                        years.append(year)

            years.sort(reverse=True)
            for year in years:
                if len(elections[year]) > 0:
                    if 'elections' not in cand_data:
                        cand_data['elections'] = []
                    cand_data['elections'].append(elections[year])

            results.append(cand_data)

        return {'api_version': "0.2", 'pagination': page_data,
                'results': results}


class CandidateResource(BaseCandidateResource, SingleResource):

    parser = reqparse.RequestParser()
    parser.add_argument(
        'fields',
        type=str,
        help='Choose the fields that are displayed'
    )
    parser.add_argument(
        'year',
        type=str,
        default=default_year(),
        help="Year in which a candidate runs for office"
    )

