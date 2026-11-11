import copy
from collections import Counter

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from documents.build_inspection import build_entries
from documents.models import DocumentTemplate, InspectionRecord
from organizations.models import Industry, Organization


class InspectionChecklistTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')
        cls.org = Organization.objects.create(name='Lista A', industry=cls.industry)
        cls.other = Organization.objects.create(name='Lista B', industry=cls.industry)
        cls.staff = User.objects.create_user(
            username='lista-a',
            password='test-pass',
            organization=cls.org,
            role=User.Role.STAFF,
            first_name='Mila',
            last_name='Radnik',
        )
        cls.other_staff = User.objects.create_user(
            username='lista-b',
            password='test-pass',
            organization=cls.other,
            role=User.Role.STAFF,
        )
        cls.admin = User.objects.create_user(
            username='lista-admin',
            password='test-pass',
            role=User.Role.PLATFORM_ADMIN,
            is_staff=True,
        )

    def start(self, code='IN-02'):
        response = self.client.post(reverse('document', args=[code]), {'action': 'start'})
        record = InspectionRecord.objects.filter(template__code=code).order_by('-pk').first()
        return response, record

    def payload(self, record, action='save', answers=None, notes=None, remarks=''):
        checklist = record.snapshot
        value = checklist['scale'][0]['value']
        data = {'action': action, 'remarks': remarks}
        for item in checklist['items']:
            if item['type'] != 'q':
                continue
            data[f"q_{item['key']}"] = value
        if answers:
            for key, chosen in answers.items():
                data[f'q_{key}'] = chosen
        if notes:
            for key, text in notes.items():
                data[f'n_{key}'] = text
        return data

    def test_questionnaires_stay_exactly_as_seeded(self):
        fresh = {entry['code']: entry for entry in build_entries()}
        expected_questions = {'IN-02': 8, 'IN-03': 79, 'IN-04': 90}
        for code, total in expected_questions.items():
            stored = DocumentTemplate.objects.get(code=code)
            self.assertEqual(stored.checklist, fresh[code]['checklist'])
            self.assertEqual(stored.body, fresh[code]['body'])
            self.assertEqual(stored.source_filename, 'Kontrolne liste latinica.xlsx')
            questions = [item for item in stored.checklist['items'] if item['type'] == 'q']
            self.assertEqual(len(questions), total)

        trace = DocumentTemplate.objects.get(code='IN-02')
        self.assertEqual([option['value'] for option in trace.checklist['scale']], ['DA', 'NE', 'NP'])
        self.assertEqual(trace.checklist['scale'][2]['meaning'], 'Nije primenljivo')
        hygiene = DocumentTemplate.objects.get(code='IN-03')
        self.assertEqual(
            [item['text'] for item in hygiene.checklist['items'] if item['type'] == 'section'][0],
            'OBJEKAT',
        )
        haccp = DocumentTemplate.objects.get(code='IN-04')
        self.assertEqual([option['value'] for option in haccp.checklist['scale']], ['A', 'B', 'V', 'G'])

    def test_get_does_not_create_and_post_without_action_is_refused(self):
        self.client.force_login(self.staff)
        url = reverse('document', args=['IN-02'])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {'q_4': 'DA'}).status_code, 403)
        self.assertEqual(InspectionRecord.objects.count(), 0)

    def test_start_creates_a_separate_run_each_time_including_the_same_day(self):
        self.client.force_login(self.staff)
        url = reverse('document', args=['IN-02'])
        first = self.client.post(url, {'action': 'start'})
        second = self.client.post(url, {'action': 'start'})
        runs = list(InspectionRecord.objects.filter(organization=self.org, template__code='IN-02'))
        self.assertEqual(len(runs), 2)
        self.assertEqual(timezone.localtime(runs[0].created_at).date(), timezone.localdate())
        self.assertEqual(timezone.localtime(runs[1].created_at).date(), timezone.localdate())
        self.assertEqual(runs[0].created_by, self.staff)
        self.assertEqual(runs[0].status, InspectionRecord.Status.OPEN)
        self.assertNotEqual(first.url, second.url)
        self.assertEqual(runs[0].snapshot, DocumentTemplate.objects.get(code='IN-02').checklist)

    def test_runs_keep_separate_answers_and_an_open_run_can_be_resumed(self):
        self.client.force_login(self.staff)
        _, first = self.start()
        _, second = self.start()
        saved = self.client.post(reverse('inspection_run', args=['IN-02', first.pk]), {
            'action': 'save',
            'q_4': 'DA',
            'q_5': 'NE',
            'n_4': '  ulaz  ',
            'remarks': '  prva  ',
        })
        self.assertRedirects(saved, reverse('document', args=['IN-02']))
        self.client.post(reverse('inspection_run', args=['IN-02', second.pk]), {
            'action': 'save',
            'q_4': 'NP',
            'remarks': 'druga',
        })
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.answers, {'4': 'DA', '5': 'NE'})
        self.assertEqual(first.notes, {'4': 'ulaz'})
        self.assertEqual(first.remarks, 'prva')
        self.assertEqual(second.answers, {'4': 'NP'})
        self.assertEqual(second.remarks, 'druga')

        page = self.client.get(reverse('inspection_run', args=['IN-02', first.pk]))
        html = page.content.decode()
        self.assertRegex(html, r'<input[^>]*name="q_4"[^>]*value="DA"[^>]*checked')
        self.assertContains(page, '2/8')
        self.assertContains(page, 'value="ulaz"')
        history = self.client.get(reverse('document', args=['IN-02']))
        self.assertContains(history, 'U toku')
        self.assertContains(history, 'Mila Radnik')
        self.assertContains(history, '2/8')
        self.assertContains(history, '1/8')

    def test_completion_locks_the_run_and_a_repeat_post_does_not_change_it(self):
        self.client.force_login(self.staff)
        _, record = self.start()
        url = reverse('inspection_run', args=['IN-02', record.pk])
        history = reverse('document', args=['IN-02'])
        partial = self.client.post(url, {'action': 'complete', 'q_4': 'DA'}, follow=True)
        record.refresh_from_db()
        self.assertEqual(record.status, InspectionRecord.Status.OPEN)
        self.assertIsNone(record.completed_at)
        self.assertContains(partial, 'sva pitanja')

        done = self.client.post(url, self.payload(record, action='complete', remarks='gotovo'))
        self.assertRedirects(done, history)
        record.refresh_from_db()
        self.assertEqual(record.status, InspectionRecord.Status.DONE)
        self.assertEqual(record.completed_by, self.staff)
        self.assertIsNotNone(record.completed_at)
        self.assertEqual(len(record.answers), 8)
        finished_at = record.completed_at
        history_page = self.client.get(history)
        self.assertContains(history_page, 'Završena')
        self.assertContains(history_page, '8/8')
        page = self.client.get(url)
        self.assertContains(page, 'Završena')
        self.assertNotContains(page, 'Sačuvaj')
        self.assertContains(page, 'disabled')

        denied = self.client.post(url, self.payload(record, action='save', answers={'4': 'NE'}))
        self.assertEqual(denied.status_code, 403)
        record.refresh_from_db()
        self.assertEqual(record.completed_at, finished_at)
        self.assertEqual(record.completed_by, self.staff)
        self.assertEqual(record.answers['4'], 'DA')
        record.answers = {'4': 'NE'}
        with self.assertRaises(ValidationError):
            record.save()

    def test_history_lists_previous_runs_and_a_new_one_can_start_after_completion(self):
        self.client.force_login(self.staff)
        _, done_run = self.start()
        self.client.post(
            reverse('inspection_run', args=['IN-02', done_run.pk]),
            self.payload(done_run, action='complete'),
        )
        self.start()
        page = self.client.get(reverse('document', args=['IN-02']))
        self.assertContains(page, 'Nova kontrola')
        self.assertContains(page, 'Završena')
        self.assertContains(page, 'U toku')
        self.assertEqual(
            InspectionRecord.objects.filter(organization=self.org, template__code='IN-02').count(),
            2,
        )

    def test_snapshot_keeps_the_questions_from_the_moment_the_run_started(self):
        self.client.force_login(self.staff)
        _, record = self.start()
        original = record.snapshot['items'][0]['text']
        template = DocumentTemplate.objects.get(code='IN-02')
        changed = copy.deepcopy(template.checklist)
        changed['items'][0]['text'] = 'IZMENJENO PITANJE KOJE NE POSTOJI'
        template.checklist = changed
        template.save(update_fields=['checklist'])

        page = self.client.get(reverse('inspection_run', args=['IN-02', record.pk]))
        self.assertContains(page, original)
        self.assertNotContains(page, 'IZMENJENO PITANJE KOJE NE POSTOJI')
        record.snapshot = changed
        with self.assertRaises(ValidationError):
            record.save()

        self.start()
        fresh = InspectionRecord.objects.exclude(pk=record.pk).get()
        self.assertEqual(fresh.snapshot['items'][0]['text'], 'IZMENJENO PITANJE KOJE NE POSTOJI')
        record.refresh_from_db()
        self.assertEqual(record.snapshot['items'][0]['text'], original)

    def test_answers_stay_inside_the_organization(self):
        self.client.force_login(self.staff)
        _, record = self.start()
        url = reverse('inspection_run', args=['IN-02', record.pk])
        self.client.post(url, {'action': 'save', 'q_4': 'DA', 'remarks': 'samo lista A'})
        library = self.client.get(reverse('inspection'))
        self.assertContains(library, 'U toku 1/8')

        self.client.force_login(self.other_staff)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'action': 'save', 'q_4': 'NE'}).status_code, 404)
        other_index = self.client.get(reverse('document', args=['IN-02']))
        self.assertContains(other_index, 'Lista B')
        self.assertNotContains(other_index, 'samo lista A')
        self.assertContains(other_index, 'Još nema kontrola')
        record.refresh_from_db()
        self.assertEqual(record.answers, {'4': 'DA'})
        self.assertFalse(
            InspectionRecord.objects.filter(organization=self.other).exists()
        )

    def test_platform_admin_needs_a_selected_organization(self):
        self.client.force_login(self.admin)
        url = reverse('document', args=['IN-02'])
        self.assertEqual(self.client.post(url, {'action': 'start'}).status_code, 403)
        self.assertEqual(InspectionRecord.objects.count(), 0)
        self.client.get(f'{url}?objekat={self.org.pk}')
        started = self.client.post(url, {'action': 'start'})
        self.assertEqual(started.status_code, 302)
        record = InspectionRecord.objects.get()
        self.assertEqual(record.organization, self.org)

    def test_csrf_blocks_creation_and_edits(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        url = reverse('document', args=['IN-02'])
        self.assertEqual(csrf_client.get(url).status_code, 200)
        self.assertEqual(csrf_client.post(url, {'action': 'start'}).status_code, 403)
        self.assertEqual(InspectionRecord.objects.count(), 0)

        self.client.force_login(self.staff)
        _, record = self.start()
        run = reverse('inspection_run', args=['IN-02', record.pk])
        self.client.post(run, {'action': 'save', 'q_4': 'DA'})
        csrf_client.force_login(self.staff)
        denied = csrf_client.post(run, {'action': 'save', 'q_4': 'NE', 'remarks': 'ne'})
        self.assertEqual(denied.status_code, 403)
        record.refresh_from_db()
        self.assertEqual(record.answers, {'4': 'DA'})
        self.assertEqual(record.remarks, '')

    def test_run_page_renders_the_original_questions_and_options(self):
        self.client.force_login(self.staff)
        for code in ('IN-02', 'IN-03', 'IN-04'):
            _, record = self.start(code)
            page = self.client.get(reverse('inspection_run', args=[code, record.pk]))
            self.assertEqual(page.status_code, 200)
            content = page.content.decode()
            counts = Counter()
            for item in record.snapshot['items']:
                if item['type'] in {'q', 'section'}:
                    counts[item['text']] += 1
            for text, count in counts.items():
                self.assertGreaterEqual(content.count(text), count, text)
            self.assertContains(page, 'Primedbe i sugestije')
            self.assertContains(page, 'Lista A')

        trace = self.client.get(reverse('inspection_run', args=['IN-02', InspectionRecord.objects.filter(template__code='IN-02').latest('pk').pk]))
        self.assertNotContains(trace, 'check-fold')
        hygiene = InspectionRecord.objects.filter(template__code='IN-03').latest('pk')
        hygiene_page = self.client.get(reverse('inspection_run', args=['IN-03', hygiene.pk]))
        self.assertContains(hygiene_page, 'check-fold')
        self.assertContains(hygiene_page, '<details class="check-fold" open>')
        haccp = self.client.get(reverse('inspection_run', args=['IN-04', InspectionRecord.objects.filter(template__code='IN-04').latest('pk').pk]))
        self.assertContains(haccp, 'value="A"')
        self.assertContains(haccp, 'U potpunosti ispunjen zahtev')
        self.assertNotContains(haccp, 'value="DA"')
        self.assertNotContains(haccp, 'value="NP"')

    def test_invalid_answer_is_ignored(self):
        self.client.force_login(self.staff)
        _, record = self.start()
        self.client.post(reverse('inspection_run', args=['IN-02', record.pk]), {
            'action': 'save',
            'q_4': 'MOZDA',
            'q_5': 'NP',
        })
        record.refresh_from_db()
        self.assertEqual(record.answers, {'5': 'NP'})
