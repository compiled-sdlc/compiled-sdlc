package org.springframework.samples.petclinic.api.boundary.web;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webflux.test.autoconfigure.WebFluxTest;
import org.springframework.cloud.circuitbreaker.resilience4j.ReactiveResilience4JAutoConfiguration;
import org.springframework.context.annotation.Import;
import org.springframework.samples.petclinic.api.application.CustomersServiceClient;
import org.springframework.samples.petclinic.api.application.VisitsServiceClient;
import org.springframework.samples.petclinic.api.dto.OwnerDetails;
import org.springframework.samples.petclinic.api.dto.PetDetails;
import org.springframework.samples.petclinic.api.dto.VisitDetails;
import org.springframework.samples.petclinic.api.dto.Visits;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.core.publisher.Mono;

import static org.mockito.ArgumentMatchers.anyList;

/**
 * Acceptance check for CR-118, gateway side: an owner with no pets costs no call.
 *
 * Passability: Skip the visits call when the owner has no pets. The fixture mocks the
 * visits client and asserts it was never called, so the saving is observable without a
 * running service.
 */
@WebFluxTest(controllers = ApiGatewayController.class)
@Import({ReactiveResilience4JAutoConfiguration.class, CircuitBreakerConfiguration.class})
class NoPetsNoLookupAcceptanceTest {

    @MockitoBean
    private CustomersServiceClient customersServiceClient;

    @MockitoBean
    private VisitsServiceClient visitsServiceClient;

    @Autowired
    private WebTestClient client;

    private OwnerDetails anOwner(int id, String firstName, List<PetDetails> pets) {
        return OwnerDetails.OwnerDetailsBuilder.anOwnerDetails()
            .id(id)
            .firstName(firstName)
            .lastName("Franklin")
            .pets(pets)
            .build();
    }

    @Test
    void shouldNotAskTheVisitsServiceAboutAnOwnerWithNoPets() {
        Mockito.when(customersServiceClient.getOwner(2))
            .thenReturn(Mono.just(anOwner(2, "Betty", new ArrayList<>())));

        client.get()
            .uri("/api/gateway/owners/2")
            .exchange()
            .expectStatus().isOk()
            .expectBody()
            .jsonPath("$.firstName").isEqualTo("Betty")
            .jsonPath("$.pets").isEmpty();

        Mockito.verify(visitsServiceClient, Mockito.never()).getVisitsForPets(anyList());
    }

    @Test
    void shouldStillAssembleAnOwnerThatHasPets() {
        PetDetails cat = PetDetails.PetDetailsBuilder.aPetDetails()
            .id(20)
            .name("Garfield")
            .visits(new ArrayList<>())
            .build();
        Mockito.when(customersServiceClient.getOwner(1))
            .thenReturn(Mono.just(anOwner(1, "George", List.of(cat))));
        Mockito.when(visitsServiceClient.getVisitsForPets(Collections.singletonList(cat.id())))
            .thenReturn(Mono.just(new Visits(List.of(new VisitDetails(300, cat.id(), null, "First visit")))));

        client.get()
            .uri("/api/gateway/owners/1")
            .exchange()
            .expectStatus().isOk()
            .expectBody()
            .jsonPath("$.pets[0].name").isEqualTo("Garfield")
            .jsonPath("$.pets[0].visits[0].description").isEqualTo("First visit");

        Mockito.verify(visitsServiceClient).getVisitsForPets(Collections.singletonList(cat.id()));
    }
}
