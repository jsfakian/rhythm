from django.core.management.base import BaseCommand
from uploads.models import Institution, UserProfile

INSTITUTIONS = [
    ("University Of Crete", "S001"),
    ("Istituto Di Ricovero E Cura A Carattere Scientifico Burlo Garofolo", "S002"),
    ("Instituto Politecnico De Coimbra", "S003"),
    ("Universitair Medisch Centrum Utrecht", "S004"),
    ("Bernu Kliniska Universitates Slimnica Valsts Sia", "S005"),
    ("Vitaz Vzw", "S006"),
    ("Universita Degli Studi Di Palermo", "S007"),
    ("Erasmus Universitair Medisch Centrum Rotterdam", "S008"),
    ("University College Dublin, National University Of Ireland, Dublin", "S009"),
    ("Univerzitetni Klinicni Center Ljubljana", "S010"),
    ("Academisch Ziekenhuis Groningen", "S012"),
    ("Spitalul Clinic De Urgenta Pentru Copii Grigore Alexandrescu", "S014"),
    ("Fundacion Privada Instituto De Salud Global Barcelona", "S015"),
    ("Fundacio Privada Per A La Recerca I La Docencia Sant Joan De Deu", "S018"),
    ("Hospital Sant Joan De Deu", "S019"),
    ("Children's Health Ireland", "S020"),
]


class Command(BaseCommand):
    help = "Seed the Institution table with RHYTHM partner institutions."

    def handle(self, *args, **options):
        created = updated = 0
        for name, code in INSTITUTIONS:
            obj, was_created = Institution.objects.update_or_create(
                site_code=code,
                defaults={"name": name},
            )
            if was_created:
                created += 1
                self.stdout.write(f"  Created  {code}  {name}")
            else:
                updated += 1
                self.stdout.write(f"  Updated  {code}  {name}")

        # Update existing UserProfile records that used the old "University of Crete" spellings
        old_names = ["Panepistimio Kritis", "university of crete", "University of Crete",
                     "PANEPISTIMIO KRITIS"]
        rows = UserProfile.objects.filter(institution__in=old_names)
        count = rows.update(institution="University Of Crete", site_code="S001")
        if count:
            self.stdout.write(f"  Updated {count} UserProfile(s) to 'University Of Crete'")

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {created} created, {updated} updated."
        ))
