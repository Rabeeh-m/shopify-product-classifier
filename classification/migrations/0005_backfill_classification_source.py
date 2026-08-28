from django.db import migrations


def backfill_source(apps, schema_editor):
    """Tag existing classifications as RULE where the product matches a
    vendor rule (mirroring the rule pass), leaving everything else as AI.

    The rule pass is deterministic: a product gets RULE iff
    try_rule_classification returns a non-None result.
    """
    Classification = apps.get_model("classification", "Classification")

    from classification.services.rules import try_rule_classification

    rule_ids = []
    qs = (
        Classification.objects.filter(source="AI")
        .select_related("product")
        .only("id", "product")
    )
    for cls in qs.iterator(chunk_size=500):
        if try_rule_classification(cls.product) is not None:
            rule_ids.append(cls.id)

    if rule_ids:
        # Values are stored as the raw choice string 'Rule'.
        Classification.objects.filter(id__in=rule_ids).update(source="Rule")


class Migration(migrations.Migration):

    dependencies = [
        ("classification", "0004_add_source_to_classification"),
    ]

    operations = [
        migrations.RunPython(backfill_source, migrations.RunPython.noop),
    ]
