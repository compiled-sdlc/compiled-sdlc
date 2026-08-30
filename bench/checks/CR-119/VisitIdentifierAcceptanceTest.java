package org.springframework.samples.petclinic.visits.web;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.visits.model.Visit;
import org.springframework.samples.petclinic.visits.model.VisitRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-119: the identifier belongs to the database, not the caller.
 *
 * Passability: Bind a request record in the web layer instead of the persistence
 * entity, and refuse a body carrying an identifier. The fixture posts such a body and
 * verifies nothing was saved; the entity stays untouched, which is what closes the one-
 * line repairs.
 * Confirmed empirically: 12 of 12 cells passed it in the full run.
 */
@WebMvcTest(VisitResource.class)
@ActiveProfiles("test")
class VisitIdentifierAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    VisitRepository visitRepository;

    private void givenTheRepositorySaves() {
        given(visitRepository.save(any(Visit.class))).willAnswer(invocation -> {
            Visit saved = invocation.getArgument(0);
            if (saved.getId() == null) {
                saved.setId(77);
            }
            return saved;
        });
    }

    @Test
    void shouldRefuseACreateThatCarriesAnIdentifier() throws Exception {
        givenTheRepositorySaves();

        mvc.perform(post("/owners/1/pets/111/visits")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"id\":999,\"description\":\"a check-up\"}"))
            .andExpect(status().isBadRequest());

        verify(visitRepository, never()).save(any(Visit.class));
    }

    @Test
    void shouldRefuseACreateThatCarriesAnIdentifierAlongsideEverythingElse() throws Exception {
        givenTheRepositorySaves();

        mvc.perform(post("/owners/1/pets/111/visits")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"id\":999,\"date\":\"2020-01-01\",\"description\":\"a check-up\",\"petId\":111}"))
            .andExpect(status().isBadRequest());

        verify(visitRepository, never()).save(any(Visit.class));
    }

    @Test
    void shouldStoreACreateThatCarriesNoIdentifierExactlyAsBefore() throws Exception {
        givenTheRepositorySaves();

        mvc.perform(post("/owners/1/pets/111/visits")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"date\":\"2020-01-01\",\"description\":\"a check-up\"}"))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.id").value(77))
            .andExpect(jsonPath("$.petId").value(111))
            .andExpect(jsonPath("$.description").value("a check-up"))
            .andExpect(jsonPath("$.date").isNotEmpty());

        ArgumentCaptor<Visit> captor = ArgumentCaptor.forClass(Visit.class);
        verify(visitRepository).save(captor.capture());
        assertThat(captor.getValue().getPetId()).isEqualTo(111);
        assertThat(captor.getValue().getDescription()).isEqualTo("a check-up");
    }
}
