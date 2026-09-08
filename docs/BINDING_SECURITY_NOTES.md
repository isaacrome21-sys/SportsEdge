# Binding security notes

Do not trust provider event IDs alone to establish MLB game identity. Upstream normalization should bind provider offers to the canonical MLB event using canonical teams plus scheduled start tolerance and preserve both the provider offer/event reference and canonical event instance. The model layer must never perform this reconciliation.
